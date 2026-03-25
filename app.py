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
from flask import Flask, jsonify
from flask_cors import CORS
from shazamio import Shazam
import pystray
from PIL import Image, ImageDraw

INITIAL_RECORD_SECONDS = 10   
NORMAL_INTERVAL = 1           

app = Flask(__name__)
CORS(app)

def log(mensagem, categoria="SISTEMA"):
    timestamp = time.strftime("%H:%M:%S")
    print(f"[{timestamp}] [{categoria}] {mensagem}")

def gravar_audio_memoria(duracao):
    CHUNK = 512
    p = pyaudio.PyAudio()
    try:
        wasapi_info = p.get_host_api_info_by_type(pyaudio.paWASAPI)
        default_speakers = p.get_device_info_by_index(wasapi_info["defaultOutputDevice"])
        
        loopback_encontrado = False
        if not default_speakers["isLoopbackDevice"]:
            for loopback in p.get_loopback_device_info_generator():
                if default_speakers["name"] in loopback["name"]:
                    default_speakers = loopback
                    loopback_encontrado = True
                    break
        
        if not loopback_encontrado and not default_speakers["isLoopbackDevice"]:
            raise Exception("Nenhum dispositivo de áudio detectado.")

        canais = default_speakers["maxInputChannels"]
        taxa = int(default_speakers["defaultSampleRate"])

        stream = p.open(format=pyaudio.paInt16, channels=canais, rate=taxa,
                        frames_per_buffer=CHUNK, input=True,
                        input_device_index=default_speakers["index"])

        frames = []
        for _ in range(0, int(taxa / CHUNK * duracao)):
            frames.append(stream.read(CHUNK))

        stream.stop_stream()
        stream.close()

        audio_buffer = io.BytesIO()
        wf = wave.open(audio_buffer, 'wb')
        wf.setnchannels(canais)
        wf.setsampwidth(p.get_sample_size(pyaudio.paInt16))
        wf.setframerate(taxa)
        wf.writeframes(b''.join(frames))
        wf.close()
        
        return audio_buffer.getvalue() 
        
    except Exception as e:
        log(f"ERRO NA GRAVAÇÃO: {e}", "ERRO")
        raise e 
    finally:
        p.terminate()

class MusicManager:
    def __init__(self):
        self.shazam = Shazam()
        self.session_id = time.time()
        self.servidor_rodando = True   
        self.reset_state()

    def reset_state(self):
        self.session_id = time.time() 
        self.artista_atual = None
        self.musica_atual = None
        self.tempo_referencia_sistema = 0.0 
        self.letra_sincronizada = []
        self.delay_manual = 0.0 
        self.escutando = False   
        self.busca_concluida = False 
        self.status_busca = "Aguardando comando..." 

    async def reconhecer_snippet(self, audio_bytes):
        try:
            resultado = await self.shazam.recognize(audio_bytes)
            if resultado and 'track' in resultado:
                track = resultado['track']
                offset_s = resultado.get('matches', [{}])[0].get('offset', 0.0)
                return track['title'], track['subtitle'], offset_s
        except Exception as e:
            log(f"Erro no Shazam: {e}", "ERRO")
        return None, None, 0.0

    def buscar_letra_lrclib(self, artista, musica):
        try:
            headers = {"User-Agent": "ProjetoFestivalApp/1.0"}
            
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
                    return extrair_linhas(dados["syncedLyrics"])
        except Exception as e:
            log(f"Erro na busca LRCLib: {e}", "ERRO")
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
        "status_msg": manager.status_busca
    })

@app.route('/iniciar', methods=['GET'])
def iniciar_escuta():
    manager.reset_state()
    manager.escutando = True
    manager.status_busca = "Ouvindo áudio do sistema..."
    return jsonify({"status": "processando"})

@app.route('/parar', methods=['GET'])
def parar_escuta():
    manager.reset_state()
    return jsonify({"status": "parado"})

async def async_worker_verificacao(manager):
    loop = asyncio.get_event_loop()
    while manager.servidor_rodando:
        if not manager.escutando or manager.busca_concluida:
            await asyncio.sleep(1)
            continue

        current_session = manager.session_id
        t_inicio_gravacao = time.time()
        
        try:
            # Captura os bytes do áudio direto da memória
            audio_bytes = await loop.run_in_executor(None, gravar_audio_memoria, INITIAL_RECORD_SECONDS)
        except Exception as e:
            # TRATAMENTO DE ERRO: Avisa o front-end que falhou
            manager.status_busca = "Erro: Áudio do sistema não detectado."
            manager.escutando = False
            continue
        
        if manager.session_id != current_session or not manager.escutando: continue

        nova_musica, novo_artista, offset_shazam = await manager.reconhecer_snippet(audio_bytes)
        
        if nova_musica and manager.escutando:
            log(f"Identificado: {nova_musica}", "LOGIC")
            manager.musica_atual = nova_musica
            manager.artista_atual = novo_artista
            manager.status_busca = "Baixando letra..."
            
            letra = await loop.run_in_executor(None, manager.buscar_letra_lrclib, novo_artista, nova_musica)
            
            if letra:
                manager.letra_sincronizada = letra
                manager.tempo_referencia_sistema = t_inicio_gravacao - offset_shazam
                manager.busca_concluida = True
                manager.status_busca = "Sincronizado"
            else:
                manager.status_busca = "Letra não encontrada."
                manager.busca_concluida = True
        
        await asyncio.sleep(NORMAL_INTERVAL)

def start_background_loop(manager):
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.run_until_complete(async_worker_verificacao(manager))

def criar_icone():
    imagem = Image.new('RGB', (64, 64), color = (74, 144, 226))
    desenho = ImageDraw.Draw(imagem)
    return imagem

def sair_do_app(icon, item):
    log("Encerrando aplicação...", "SISTEMA")
    manager.servidor_rodando = False
    icon.stop()
    os._exit(0) 
def iniciar_bandeja():
    menu = pystray.Menu(pystray.MenuItem('Sair do Projeto Festival', sair_do_app))
    icone = pystray.Icon("ProjetoFestival", criar_icone(), "Projeto Festival (Servidor)", menu)
    icone.run()

if __name__ == "__main__":
    import logging
    log_flask = logging.getLogger('werkzeug')
    log_flask.disabled = True
    
    threading.Thread(target=lambda: app.run(port=5000, debug=False, use_reloader=False), daemon=True).start()
    
    threading.Thread(target=start_background_loop, args=(manager,), daemon=True).start()
    
    log("Servidor rodando em segundo plano. Verifique o ícone na bandeja.")

    iniciar_bandeja()