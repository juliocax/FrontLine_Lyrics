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
from PIL import Image, ImageTk, ImageEnhance
from deep_translator import GoogleTranslator
import tkinter as tk

NORMAL_INTERVAL = 2           

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
        
        self.letra_original = []
        self.traducoes_cacheadas = {} 
        self.idioma_atual = "original"
        self.letra_sincronizada = []
        
        self.delay_manual = 0.0 
        self.escutando = False   
        self.busca_concluida = False 
        self.status_busca = "Alt + M to hide" 
        self.letra_pausada = False
        self.momento_pausa = 0.0

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

    def limpar_nome_musica(self, texto):
        if not texto: return ""
        texto_limpo = re.sub(r'\(.*?(feat|remaster|radio edit|mix|version).*?\)', '', texto, flags=re.IGNORECASE)
        texto_limpo = re.sub(r'-.*?(remaster|radio edit|mix|version).*', '', texto_limpo, flags=re.IGNORECASE)
        return texto_limpo.strip()

    def buscar_letra_lrclib(self, artista, musica):
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

        try:
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
            log(f"LRCLib exact search error: {e}", "ERROR")

        artista_limpo = self.limpar_nome_musica(artista)
        musica_limpa = self.limpar_nome_musica(musica)
        
        if artista_limpo != artista or musica_limpa != musica:
            log(f"Fallback 1: Tentando nomes limpos ({artista_limpo} - {musica_limpa})", "LOGIC")
            try:
                r = requests.get(url_get, params={"artist_name": artista_limpo, "track_name": musica_limpa}, headers=headers, timeout=5)
                if r.status_code == 200:
                    dados = r.json()
                    if dados.get("syncedLyrics"):
                        linhas = extrair_linhas(dados["syncedLyrics"])
                        if linhas:
                            linhas.append({"tempo": linhas[-1]["tempo"] + 5.0, "letra": "End"})
                            return linhas
            except Exception as e:
                pass 

        log(f"Fallback 2: Usando busca ampla para: {musica_limpa} {artista_limpo}", "LOGIC")
        try:
            url_search = "https://lrclib.net/api/search"
            query = f"{musica_limpa} {artista_limpo}" 
            r = requests.get(url_search, params={"q": query}, headers=headers, timeout=7)
            
            if r.status_code == 200:
                resultados = r.json()
                if isinstance(resultados, list):
                    for item in resultados:
                        if item.get("syncedLyrics"):
                            log(f"Letra encontrada via Search Fallback! (ID: {item.get('id')})", "LOGIC")
                            linhas = extrair_linhas(item["syncedLyrics"])
                            if linhas:
                                linhas.append({"tempo": linhas[-1]["tempo"] + 5.0, "letra": "End"})
                                return linhas
        except Exception as e:
            log(f"LRCLib search fallback error: {e}", "ERROR")

        log("Todas as tentativas de buscar a letra falharam.", "WARNING")
        return None

    def gerar_traducao(self, idioma_alvo):
        if not self.letra_original: return False
        if idioma_alvo in self.traducoes_cacheadas: 
            return True 
            
        try:
            log(f"Traduzindo letra para: {idioma_alvo.upper()}", "LOGIC")
            textos = [item['letra'] for item in self.letra_original]
            texto_completo = "\n".join(textos)
            
            texto_traduzido = GoogleTranslator(source='auto', target=idioma_alvo).translate(texto_completo)
            textos_separados = texto_traduzido.split('\n')
            
            linhas_traduzidas = []
            for i, item in enumerate(self.letra_original):
                letra_trad = textos_separados[i] if i < len(textos_separados) else item['letra']
                linhas_traduzidas.append({"tempo": item['tempo'], "letra": letra_trad})
                
            self.traducoes_cacheadas[idioma_alvo] = linhas_traduzidas
            return True
        except Exception as e:
            log(f"Erro na tradução para {idioma_alvo}: {e}", "ERROR")
            return False

manager = MusicManager()

@app.route('/status', methods=['GET'])
def get_status():
    linha_atual = ""
    linha_anterior = ""
    linha_futura = ""
    
    if manager.letra_sincronizada:
        tempo_base = manager.momento_pausa if manager.letra_pausada else time.time()
        tempo_decorrido = (tempo_base - manager.tempo_referencia_sistema) + manager.delay_manual
        
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
        "letra_encontrada": len(manager.letra_sincronizada) > 0,
        "pausado": manager.letra_pausada,
        "idioma": manager.idioma_atual 
    })

@app.route('/iniciar', methods=['GET'])
def iniciar_escuta():
    manager.reset_state()
    manager.escutando = True
    manager.status_busca = "Alt + M to hide"
    return jsonify({"status": "processando"})

@app.route('/parar', methods=['GET'])
def parar_escuta():
    manager.reset_state()
    return jsonify({"status": "parado"})

@app.route('/toggle_pause', methods=['GET'])
def toggle_pause():
    if not manager.letra_sincronizada:
        return jsonify({"status": "erro", "mensagem": "Nenhuma letra ativa"})
        
    if manager.letra_pausada:
        tempo_parado = time.time() - manager.momento_pausa
        manager.tempo_referencia_sistema += tempo_parado
        manager.letra_pausada = False
    else:
        manager.letra_pausada = True
        manager.momento_pausa = time.time()
        
    return jsonify({"status": "sucesso", "pausado": manager.letra_pausada})

@app.route('/mudar_idioma', methods=['GET'])
def mudar_idioma():
    lang = request.args.get('lang', 'original')
    
    if not manager.letra_original:
        return jsonify({"status": "erro", "mensagem": "No lyrics loaded"})
        
    if lang == "original":
        manager.letra_sincronizada = manager.letra_original
        manager.idioma_atual = "original"
    else:
        sucesso = manager.gerar_traducao(lang)
        if sucesso:
            manager.letra_sincronizada = manager.traducoes_cacheadas[lang]
            manager.idioma_atual = lang
        else:
            return jsonify({"status": "erro", "mensagem": "Translation failed"})
            
    return jsonify({"status": "sucesso", "idioma": manager.idioma_atual})

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
        manager.letra_pausada = False 
        manager.momento_pausa = 0.0
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
        manager.letra_original = letra
        manager.letra_sincronizada = letra
        manager.traducoes_cacheadas = {} 
        manager.idioma_atual = "original"
        
        manager.musica_atual = musica
        manager.artista_atual = artista
        manager.escutando = True  
        manager.tempo_referencia_sistema = time.time()
        manager.delay_manual = 0.0
        manager.status_busca = "Alt + M to hide"
        manager.letra_pausada = False
        return jsonify({"status": "sucesso", "letra_completa": letra})
    else:
        manager.status_busca = "Alt + M to hide"
        return jsonify({"status": "erro", "mensagem": "Lyrics not found"}), 404

async def async_worker_verificacao(manager):
    loop = asyncio.get_event_loop()
    tempo_gravacao_atual = 4 
    tentativas_sem_sucesso = 0

    while manager.servidor_rodando:
        if not manager.escutando or manager.busca_concluida:
            tempo_gravacao_atual = 4 
            tentativas_sem_sucesso = 0
            await asyncio.sleep(1)
            continue

        current_session = manager.session_id
        t_inicio_gravacao = time.time()
        
        try:
            audio_bytes = await loop.run_in_executor(None, manager.gravar_audio_memoria, tempo_gravacao_atual)
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
            
            tempo_gravacao_atual = 4 
            tentativas_sem_sucesso = 0
            
            letra = await loop.run_in_executor(None, manager.buscar_letra_lrclib, novo_artista, nova_musica)
            manager.busca_concluida = True
            manager.status_busca = "Alt + M to hide"
            
            if letra:
                manager.letra_original = letra
                manager.letra_sincronizada = letra
                manager.traducoes_cacheadas = {} 
                manager.idioma_atual = "original"
                manager.tempo_referencia_sistema = t_inicio_gravacao - offset_shazam
            else:
                pass
        else:
            tentativas_sem_sucesso += 1
            if tentativas_sem_sucesso <= 2:
                tempo_gravacao_atual = 4
                msg_amigavel = "Listening closely..."
            else:
                tempo_gravacao_atual = min(4 + (tentativas_sem_sucesso - 2), 10)
                if tempo_gravacao_atual < 7:
                    msg_amigavel = "Analyzing audio details..."
                elif tempo_gravacao_atual < 10:
                    msg_amigavel = "Still trying to catch the beat..."
                else:
                    msg_amigavel = "Audio is tricky! Try Manual Search."
                    
            if manager.escutando:
                manager.status_busca = msg_amigavel
        
        await asyncio.sleep(NORMAL_INTERVAL)

def start_background_loop(manager):
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.run_until_complete(async_worker_verificacao(manager))

def criar_icone():
    caminho_imagem = resource_path("logo.ico")
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

# --- NOVA JANELA DE AVISO COM IMAGEM DE FUNDO ---
def mostrar_aviso_servidor():
    root = tk.Tk()
    root.overrideredirect(True) 
    root.attributes('-topmost', True) 
    
    largura = 450
    altura = 220
    tela_largura = root.winfo_screenwidth()
    tela_altura = root.winfo_screenheight()
    x = (tela_largura // 2) - (largura // 2)
    y = (tela_altura // 2) - (altura // 2)
    
    root.geometry(f"{largura}x{altura}+{x}+{y}")
    
    canvas = tk.Canvas(root, width=largura, height=altura, highlightthickness=0)
    canvas.pack(fill="both", expand=True)
    
    try:
        caminho_img = resource_path("../assets/promo.png")
        img_original = Image.open(caminho_img)
        img_redimensionada = img_original.resize((largura, altura), Image.Resampling.LANCZOS)
        
        enhancer = ImageEnhance.Brightness(img_redimensionada)
        img_escura = enhancer.enhance(0.4)
        
        bg_image = ImageTk.PhotoImage(img_escura)
        canvas.create_image(0, 0, image=bg_image, anchor="nw")
        canvas.image = bg_image 
    except Exception as e:
        canvas.configure(bg='#1a1a1a')
        log(f"Imagem de fundo não encontrada ou erro: {e}", "WARNING")

    canvas.create_text(
        largura // 2, (altura // 2) - 30,
        text="FrontLine Lyrics Server is Active!",
        fill="#ffffff", font=("Segoe UI", 14, "bold"), justify="center"
    )
    
    canvas.create_text(
        largura // 2, (altura // 2),
        text="The engine is running quietly in your system tray.",
        fill="#a0a0a0", font=("Segoe UI", 10), justify="center"
    )
    
    btn_ok = tk.Button(
        root, text="Got it!", command=root.destroy,
        bg="#a0a0a0", fg="#111", font=("Segoe UI", 10, "bold"),
        relief="flat", padx=20, pady=4, cursor="hand2",
        activebackground="#5a5a5a"
    )
    canvas.create_window(largura // 2, (altura // 2) + 50, window=btn_ok)
    
    root.mainloop()

if __name__ == "__main__":
    import logging
    log_flask = logging.getLogger('werkzeug')
    log_flask.disabled = True
    
    threading.Thread(target=mostrar_aviso_servidor, daemon=True).start()
    
    threading.Thread(target=lambda: app.run(port=5000, debug=False, use_reloader=False), daemon=True).start()
    threading.Thread(target=start_background_loop, args=(manager,), daemon=True).start()
    
    log("Server running in the background. Check the tray icon.")
    iniciar_bandeja()