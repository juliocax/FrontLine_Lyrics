import asyncio
import time
import requests
import re
import pyaudiowpatch as pyaudio
import wave
import threading
import io
import sys
import os
from flask import Flask, jsonify, request
from shazamio import Shazam
import pystray
from PIL import Image

INITIAL_RECORD_SECONDS = 10   
NORMAL_INTERVAL = 1           

app = Flask(__name__)

@app.before_request
def verificar_origem():
    origin = request.headers.get('Origin')
    if origin and not origin.startswith('chrome-extension://'):
        log(f"Access attempt blocked from origin: {origin}", "SECURITY")
        return jsonify({"erro": "Unauthorized access."}), 403

def resource_path(relative_path):
    try:
        base_path = sys._MEIPASS
    except Exception:
        base_path = os.path.abspath(".")
    return os.path.join(base_path, relative_path)

def log(mensagem, categoria="SYSTEM"):
    timestamp = time.strftime("%H:%M:%S")
    print(f"[{timestamp}] [{categoria}] {mensagem}")

class MusicManager:
    def __init__(self):
        self.shazam = Shazam()
        self.session_id = time.time()
        self.servidor_rodando = True   
        self.pyaudio_instance = pyaudio.PyAudio()
        self.device_info = self._configurar_loopback()
        
        self.reset_state()

    def _configurar_loopback(self):
        try:
            wasapi_info = self.pyaudio_instance.get_host_api_info_by_type(pyaudio.paWASAPI)
            default_speakers = self.pyaudio_instance.get_device_info_by_index(wasapi_info["defaultOutputDevice"])
            
            if not default_speakers["isLoopbackDevice"]:
                for loopback in self.pyaudio_instance.get_loopback_device_info_generator():
                    if default_speakers["name"] in loopback["name"]:
                        return loopback
            
            if not default_speakers["isLoopbackDevice"]:
                raise Exception("No loopback device detected.")
                
            return default_speakers
        except Exception as e:
            log(f"Error configuring audio: {e}", "ERROR")
            return None

    def gravar_audio_memoria(self, duracao):
        if not self.device_info:
            raise Exception("Audio device not configured correctly.")
            
        CHUNK = 512
        canais = self.device_info["maxInputChannels"]
        taxa = int(self.device_info["defaultSampleRate"])

        try:
            stream = self.pyaudio_instance.open(
                format=pyaudio.paInt16, 
                channels=canais, 
                rate=taxa,
                frames_per_buffer=CHUNK, 
                input=True,
                input_device_index=self.device_info["index"]
            )

            frames = []
            for _ in range(0, int(taxa / CHUNK * duracao)):
                frames.append(stream.read(CHUNK))

            stream.stop_stream()
            stream.close()

            audio_buffer = io.BytesIO()
            wf = wave.open(audio_buffer, 'wb')
            wf.setnchannels(canais)
            wf.setsampwidth(self.pyaudio_instance.get_sample_size(pyaudio.paInt16))
            wf.setframerate(taxa)
            wf.writeframes(b''.join(frames))
            wf.close()
            
            return audio_buffer.getvalue() 
            
        except Exception as e:
            log(f"RECORDING ERROR: {e}", "ERROR")
            raise e 

    def encerrar_audio(self):
        self.pyaudio_instance.terminate()

    def reset_state(self):
        self.session_id = time.time() 
        self.artista_atual = None
        self.musica_atual = None
        self.tempo_referencia_sistema = 0.0 
        self.letra_sincronizada = []
        self.delay_manual = 0.0 
        self.escutando = False   
        self.busca_concluida = False 
        self.status_busca = "Alt + M to hide" 

    async def reconhecer_snippet(self, audio_bytes):
        try:
            resultado = await self.shazam.recognize(audio_bytes)
            if resultado and 'track' in resultado:
                track = resultado['track']
                offset_s = resultado.get('matches', [{}])[0].get('offset', 0.0)
                return track['title'], track['subtitle'], offset_s
        except Exception as e:
            log(f"Shazam error: {e}", "ERROR")
        return None, None, 0.0

    def buscar_letra_lrclib(self, artista, musica):
        try:
            headers = {"User-Agent": "FrontLineLyricsApp/1.0"}
            
            def extrair_linhas(synced_lyrics):
                linhas = []
                padrao = re.compile(r'\[(\d{2,}):(\d{2}(?:\.\d{1,3})?)\](.*)')
                for linha in synced_lyrics.split('\n'):
                    match = padrao.match(linha)
                    if match:
                        tempo = (int(match.group(1)) * 60) + float(match.group(2))
                        texto = match.group(3).strip()
                        if texto: linhas.append({"tempo": tempo, "letra": texto})
                return linhas

            url_get = "https://lrclib.net/api/get"
            r = requests.get(url_get, params={"artist_name": artista, "track_name": musica}, headers=headers, timeout=5)
            
            if r.status_code == 200:
                dados = r.json()
                if dados.get("syncedLyrics"):
                    linhas = extrair_linhas(dados["syncedLyrics"])
                    if linhas:
                        linhas.append({"tempo": linhas[-1]["tempo"] + 5.0, "letra": "End"})
                    return linhas
            
            elif r.status_code == 429:
                log("Warning: LRCLib request limit reached.", "WARNING")
                return [{"tempo": 0.0, "letra": "Lyrics server overloaded. Please wait."}]
                
        except Exception as e:
            log(f"LRCLib search error: {e}", "ERROR")
        return None

manager = MusicManager()

@app.route('/status', methods=['GET'])
def get_status():
    linha_atual = ""
    linha_anterior = ""
    linha_futura = ""
    
    if manager.letra_sincronizada:
        tempo_decorrido = (time.time() - manager.tempo_referencia_sistema) + manager.delay_manual
        
        for i, item in enumerate(manager.letra_sincronizada):
            if tempo_decorrido >= item['tempo']:
                linha_atual = item['letra']
                linha_anterior = manager.letra_sincronizada[i-1]['letra'] if i > 0 else ""
                if i + 1 < len(manager.letra_sincronizada):
                    linha_futura = manager.letra_sincronizada[i+1]['letra']
            else:
                break
                
    return jsonify({
        "escutando": manager.escutando,
        "musica": manager.musica_atual,
        "artista": manager.artista_atual,
        "linha_atual": linha_atual,
        "linha_anterior": linha_anterior,
        "linha_futura": linha_futura,
        "status_msg": manager.status_busca,
        "busca_concluida": manager.busca_concluida,
        "letra_encontrada": len(manager.letra_sincronizada) > 0
    })

@app.route('/iniciar', methods=['GET'])
def iniciar_escuta():
    manager.reset_state()
    manager.escutando = True
    manager.status_busca = "Listening..."
    return jsonify({"status": "processando"})

@app.route('/parar', methods=['GET'])
def parar_escuta():
    manager.reset_state()
    return jsonify({"status": "parado"})

@app.route('/letra_completa', methods=['GET'])
def get_letra_completa():
    if manager.letra_sincronizada:
        return jsonify({
            "status": "sucesso",
            "letra": manager.letra_sincronizada
        })
    return jsonify({"status": "erro", "mensagem": "No lyrics loaded"})

@app.route('/sincronizar_manual', methods=['GET'])
def sincronizar_manual():
    tempo = request.args.get('tempo', type=float)
    if tempo is not None:
        manager.tempo_referencia_sistema = time.time() - tempo
        manager.delay_manual = 0.0
        return jsonify({"status": "sucesso"})
    return jsonify({"status": "erro"}), 400

@app.route('/buscar_manual', methods=['GET'])
def buscar_manual():
    artista = request.args.get('artista')
    musica = request.args.get('musica')
    
    if not artista or not musica:
        return jsonify({"status": "erro", "mensagem": "Missing parameters"}), 400
        
    letra = manager.buscar_letra_lrclib(artista, musica)
    manager.busca_concluida = True
    
    if letra:
        manager.letra_sincronizada = letra
        manager.musica_atual = musica
        manager.artista_atual = artista
        manager.escutando = True  
        manager.tempo_referencia_sistema = time.time()
        manager.delay_manual = 0.0
        manager.status_busca = "Alt + M to hide"
        return jsonify({"status": "sucesso", "letra_completa": letra})
    else:
        manager.status_busca = "Alt + M to hide"
        return jsonify({"status": "erro", "mensagem": "Lyrics not found"}), 404

async def async_worker_verificacao(manager):
    loop = asyncio.get_event_loop()
    while manager.servidor_rodando:
        if not manager.escutando or manager.busca_concluida:
            await asyncio.sleep(1)
            continue

        current_session = manager.session_id
        t_inicio_gravacao = time.time()
        
        try:
            audio_bytes = await loop.run_in_executor(None, manager.gravar_audio_memoria, INITIAL_RECORD_SECONDS)
        except Exception as e:
            log(f"Error capturing audio. Attempting to reconfigure device...", "WARNING")
            manager.status_busca = "Audio disconnected. Reconnecting..."
            manager.device_info = manager._configurar_loopback()
            await asyncio.sleep(2)
            continue
        
        if manager.session_id != current_session or not manager.escutando: continue

        nova_musica, novo_artista, offset_shazam = await manager.reconhecer_snippet(audio_bytes)
        
        if nova_musica and manager.escutando:
            log(f"Identified: {nova_musica}", "LOGIC")
            manager.musica_atual = nova_musica
            manager.artista_atual = novo_artista
            manager.status_busca = "Fetching lyrics..."
            
            letra = await loop.run_in_executor(None, manager.buscar_letra_lrclib, novo_artista, nova_musica)
            manager.busca_concluida = True
            manager.status_busca = "Alt + M to hide"
            
            if letra:
                manager.letra_sincronizada = letra
                manager.tempo_referencia_sistema = t_inicio_gravacao - offset_shazam
            else:
                pass
        
        await asyncio.sleep(NORMAL_INTERVAL)

def start_background_loop(manager):
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.run_until_complete(async_worker_verificacao(manager))

def criar_icone():
    caminho_imagem = resource_path("logo48.png")
    try:
        imagem = Image.open(caminho_imagem)
    except:
        imagem = Image.new('RGB', (64, 64), color=(74, 144, 226))
    return imagem

def sair_do_app(icon, item):
    log("Closing application...", "SYSTEM")
    manager.servidor_rodando = False
    manager.encerrar_audio()
    icon.stop()
    os._exit(0)

def iniciar_bandeja():
    menu = pystray.Menu(pystray.MenuItem('Quit FrontLine Lyrics', sair_do_app))
    icone = pystray.Icon("FrontLineLyrics", criar_icone(), "FrontLine Lyrics (Server)", menu)
    icone.run()

if __name__ == "__main__":
    import logging
    log_flask = logging.getLogger('werkzeug')
    log_flask.disabled = True
    
    threading.Thread(target=lambda: app.run(port=5000, debug=False, use_reloader=False), daemon=True).start()
    
    threading.Thread(target=start_background_loop, args=(manager,), daemon=True).start()
    
    log("Server running in the background. Check the tray icon.")

    iniciar_bandeja()