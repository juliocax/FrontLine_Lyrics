import sys
import time
import asyncio
import threading
import requests
import re
import wave
import io
import traceback
import json
import websockets
import subprocess
import pyaudiowpatch as pyaudio
from shazamio import Shazam
from deep_translator import GoogleTranslator
import socket
from PyQt6.QtWidgets import (QApplication, QWidget, QVBoxLayout, QHBoxLayout, 
                             QLabel, QPushButton, QLineEdit, QComboBox, 
                             QListWidget, QListWidgetItem, QFrame)
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QFont

# --- ESCUDO CONTRA CRASH SILENCIOSO ---
def controle_de_erros(exctype, value, tb):
    print("=== ERRO CRÍTICO ENCONTRADO ===")
    traceback.print_exception(exctype, value, tb)
sys.excepthook = controle_de_erros

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
        
        # Variáveis controladas pelo Painel
        self.overlay_font_size = 26
        self.modo_fantasma = False # Começa falso para você poder arrumar o overlay na tela
        
        self.reset_state()

    def _configurar_loopback(self):
        try:
            wasapi_info = self.pyaudio_instance.get_host_api_info_by_type(pyaudio.paWASAPI)
            default_speakers = self.pyaudio_instance.get_device_info_by_index(wasapi_info["defaultOutputDevice"])
            
            if not default_speakers["isLoopbackDevice"]:
                for loopback in self.pyaudio_instance.get_loopback_device_info_generator():
                    if default_speakers["name"] in loopback["name"]:
                        return loopback
            return default_speakers
        except Exception as e:
            log(f"Error configuring audio: {e}", "ERROR")
            return None

    def gravar_audio_memoria(self, duracao):
        if not self.device_info: raise Exception("Audio device error.")
        CHUNK, canais, taxa = 512, self.device_info["maxInputChannels"], int(self.device_info["defaultSampleRate"])
        stream = self.pyaudio_instance.open(format=pyaudio.paInt16, channels=canais, rate=taxa,
                                            frames_per_buffer=CHUNK, input=True, input_device_index=self.device_info["index"])
        frames = [stream.read(CHUNK) for _ in range(0, int(taxa / CHUNK * duracao))]
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

    def reset_state(self):
        self.session_id = time.time() 
        self.artista_atual, self.musica_atual = None, None
        self.tempo_referencia_sistema = 0.0 
        self.letra_original, self.letra_sincronizada = [], []
        self.traducoes_cacheadas = {} 
        self.idioma_atual = "original"
        self.delay_manual = 0.0 
        self.escutando, self.busca_concluida, self.letra_pausada = False, False, False
        self.status_busca = "Ready. Click Listen."
        self.momento_pausa = 0.0

    async def reconhecer_snippet(self, audio_bytes):
        try:
            resultado = await self.shazam.recognize(audio_bytes)
            if resultado and 'track' in resultado:
                track = resultado['track']
                return track['title'], track['subtitle'], resultado.get('matches', [{}])[0].get('offset', 0.0)
        except Exception as e: log(f"Shazam error: {e}", "ERROR")
        return None, None, 0.0

    def buscar_letra_lrclib(self, artista, musica):
        headers = {"User-Agent": "FrontLineLyricsApp/2.0"}
        
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

        musica_limpa = re.sub(r'\([^)]*\)', '', musica).strip()
        artista_limpo = artista.split('feat.')[0].split('&')[0].strip()
        
        buscas = [
            {"track_name": musica_limpa, "artist_name": artista_limpo}, # Tentativa 1: Busca exata
            f"{musica_limpa} {artista_limpo}",                          # Tentativa 2: Termos misturados
            musica_limpa                                                # Tentativa 3: SÓ a música (O que salvou na sua print)
        ]

        try:
            r = requests.get("https://lrclib.net/api/get", params=buscas[0], headers=headers, timeout=5)
            if r.status_code == 200 and r.json().get("syncedLyrics"):
                linhas = extrair_linhas(r.json()["syncedLyrics"])
                if linhas:
                    linhas.append({"tempo": linhas[-1]["tempo"] + 5.0, "letra": "End"})
                    return linhas
        except Exception: pass
        
        for query in buscas[1:]:
            try:
                r = requests.get("https://lrclib.net/api/search", params={"q": query}, headers=headers, timeout=7)
                if r.status_code == 200:
                    resultados = r.json()
                    for item in resultados:
                        if isinstance(item, dict) and item.get("syncedLyrics"):
                            linhas = extrair_linhas(item["syncedLyrics"])
                            if linhas:
                                linhas.append({"tempo": linhas[-1]["tempo"] + 5.0, "letra": "End"})
                                return linhas
            except Exception: pass
            
        return None

    def gerar_traducao(self, idioma_alvo):
        if not self.letra_original: return False
        if idioma_alvo in self.traducoes_cacheadas: return True 
        try:
            texto_completo = "\n".join([item['letra'] for item in self.letra_original])
            texto_traduzido = GoogleTranslator(source='auto', target=idioma_alvo).translate(texto_completo).split('\n')
            linhas_traduzidas = []
            for i, item in enumerate(self.letra_original):
                letra_trad = texto_traduzido[i] if i < len(texto_traduzido) else item['letra']
                linhas_traduzidas.append({"tempo": item['tempo'], "letra": letra_trad})
            self.traducoes_cacheadas[idioma_alvo] = linhas_traduzidas
            return True
        except Exception: return False

    def obter_estado_atual(self):
        linha_atual, linha_anterior, linha_futura = "", "", ""
        
        # ESTADO 1: Parado ou escutando ambiente
        if not self.escutando or (self.escutando and not self.musica_atual):
            overlay_atual = "🎵 Waiting for the next song..."

        # ESTADO 2: Achou a música, baixando a letra
        elif self.musica_atual and not self.busca_concluida:
            overlay_atual = f"Synchronizing lyrics for '{self.musica_atual}'..."

        # ESTADO 3: Busca terminou, letra não existe
        elif self.busca_concluida and not self.letra_sincronizada:
            overlay_atual = "❌ Lyrics not found for this song."

        # ESTADO 4: Sucesso
        elif self.letra_sincronizada:
            tempo_base = self.momento_pausa if self.letra_pausada else time.time()
            tempo_decorrido = (tempo_base - self.tempo_referencia_sistema) + self.delay_manual
            
            for i, item in enumerate(self.letra_sincronizada):
                if tempo_decorrido >= item['tempo']:
                    linha_atual = item['letra']
                    linha_anterior = self.letra_sincronizada[i-1]['letra'] if i > 0 else ""
                    linha_futura = self.letra_sincronizada[i+1]['letra'] if i + 1 < len(self.letra_sincronizada) else ""
                else: break

            overlay_atual = linha_atual or "♫"

        return {
            "letra_atual": overlay_atual,
            "letra_anterior": linha_anterior,
            "letra_futura": linha_futura,
            "tamanho_fonte": self.overlay_font_size,
            "modo_fantasma": self.modo_fantasma
        }

manager = MusicManager()

async def async_worker_verificacao(manager):
    loop = asyncio.get_event_loop()
    tempo_gravacao_atual = 4 
    tentativas = 0
    while manager.servidor_rodando:
        if not manager.escutando or manager.busca_concluida:
            tempo_gravacao_atual = 4 
            tentativas = 0
            await asyncio.sleep(1)
            continue

        current_session = manager.session_id
        t_inicio_gravacao = time.time()
        try:
            audio_bytes = await loop.run_in_executor(None, manager.gravar_audio_memoria, tempo_gravacao_atual)
        except Exception:
            manager.status_busca = "Audio disconnected. Reconnecting..."
            manager.device_info = manager._configurar_loopback()
            await asyncio.sleep(2)
            continue
        
        if manager.session_id != current_session or not manager.escutando: continue
        nova_musica, novo_artista, offset_shazam = await manager.reconhecer_snippet(audio_bytes)
        
        if nova_musica and manager.escutando:
            manager.musica_atual, manager.artista_atual = nova_musica, novo_artista
            manager.status_busca = "Fetching lyrics..."
            tempo_gravacao_atual, tentativas = 4, 0
            letra = await loop.run_in_executor(None, manager.buscar_letra_lrclib, novo_artista, nova_musica)
            manager.busca_concluida = True
            manager.status_busca = "Listening..."
            if letra:
                manager.letra_original = manager.letra_sincronizada = letra
                manager.traducoes_cacheadas = {} 
                manager.idioma_atual = "original"
                manager.tempo_referencia_sistema = t_inicio_gravacao - offset_shazam
        else:
            tentativas += 1
            if tentativas <= 2: manager.status_busca = "Listening closely..."
            elif tentativas < 4: manager.status_busca = "Analyzing audio details..."
            else: manager.status_busca = "Audio is tricky! Try Manual Search."
        await asyncio.sleep(2)

clientes_conectados = set()

async def ws_handler(websocket):
    clientes_conectados.add(websocket)
    try:
        await websocket.wait_closed()
    finally:
        clientes_conectados.remove(websocket)

async def broadcast_estado_ui(manager):
    while manager.servidor_rodando:
        if clientes_conectados:
            estado = manager.obter_estado_atual()
            mensagem = json.dumps(estado)
            websockets.broadcast(clientes_conectados, mensagem)
        await asyncio.sleep(0.1)

async def main_background(manager, porta):
    asyncio.create_task(async_worker_verificacao(manager))
    asyncio.create_task(broadcast_estado_ui(manager))
    # Usa a porta que foi passada em vez da 8765 fixa
    async with websockets.serve(ws_handler, "localhost", porta):
        await asyncio.Future()

def start_background_loop(porta):
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.run_until_complete(main_background(manager, porta))

# ==========================================
# O SEU PAINEL EM PYQT DE VOLTA
# ==========================================
STYLESHEET = """
QWidget { background-color: #1a1a1a; color: #e0e0e0; font-family: 'Segoe UI'; }
QPushButton { background-color: #2d2d2d; border: 1px solid #444; border-radius: 4px; padding: 8px; font-weight: bold; font-size: 11px; text-transform: uppercase; }
QPushButton:hover { background-color: #3d3d3d; border-color: #555; }
QPushButton:disabled { color: #555; background-color: #1a1a1a; }
QLineEdit, QComboBox, QListWidget { background-color: #111; border: 1px solid #444; border-radius: 4px; padding: 6px; color: white; }
QListWidget::item:hover { background-color: #222; }
QListWidget::item:selected { background-color: #3d3d3d; }
"""

class ControlWindow(QWidget):
    def __init__(self, manager, overlay_process=None):
        super().__init__()
        self.manager = manager
        self.overlay_process = overlay_process
        self.setWindowTitle("FrontLine Control Panel")
        
        self.setWindowTitle("FrontLine Control Panel")
        self.setStyleSheet(STYLESHEET)
        self.resize(380, 600)

        layout = QVBoxLayout(self)

        self.lbl_status_icon = QLabel("●")
        self.lbl_status_icon.setStyleSheet("color: #a08d4c; font-size: 16px;")
        
        info_frame = QFrame()
        info_frame.setStyleSheet("background: #2d2d2d; border-radius: 6px;")
        info_layout = QVBoxLayout(info_frame)
        self.lbl_musica = QLabel("Stopped")
        self.lbl_musica.setFont(QFont("Segoe UI", 14, QFont.Weight.Bold))
        self.lbl_musica.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_artista = QLabel("---")
        self.lbl_artista.setStyleSheet("color: #888;")
        self.lbl_artista.setAlignment(Qt.AlignmentFlag.AlignCenter)
        info_layout.addWidget(self.lbl_musica)
        info_layout.addWidget(self.lbl_artista)
        layout.addWidget(info_frame)

        btn_layout = QHBoxLayout()
        self.btn_listen = QPushButton("Listen")
        self.btn_pause = QPushButton("⏸️ Pause")
        self.btn_pause.hide()
        self.cb_lang = QComboBox()
        self.cb_lang.addItems(["🌐 Original", "🇧🇷 Pt-Br", "🇪🇸 Español", "🇺🇸 English"])
        self.cb_lang.hide()
        self.btn_stop = QPushButton("Stop")
        
        btn_layout.addWidget(self.btn_listen)
        btn_layout.addWidget(self.btn_pause)
        btn_layout.addWidget(self.cb_lang)
        btn_layout.addWidget(self.btn_stop)
        layout.addLayout(btn_layout)

        self.btn_manual_sync = QPushButton("Manual Sync")
        self.btn_manual_sync.hide()
        layout.addWidget(self.btn_manual_sync)

        self.list_letras = QListWidget()
        self.list_letras.hide()
        layout.addWidget(self.list_letras)

        busca_frame = QFrame()
        busca_layout = QVBoxLayout(busca_frame)
        self.ipt_artista = QLineEdit()
        self.ipt_artista.setPlaceholderText("Artist")
        self.ipt_musica = QLineEdit()
        self.ipt_musica.setPlaceholderText("Song")
        self.btn_buscar = QPushButton("Search Manual")
        busca_layout.addWidget(self.ipt_artista)
        busca_layout.addWidget(self.ipt_musica)
        busca_layout.addWidget(self.btn_buscar)
        layout.addWidget(busca_frame)

        settings_frame = QFrame()
        settings_frame.setStyleSheet("border-top: 1px solid #444; margin-top: 10px;")
        set_layout = QVBoxLayout(settings_frame)
        lbl_set = QLabel("OVERLAY SETTINGS")
        lbl_set.setStyleSheet("color: #888; font-size: 10px; font-weight: bold;")
        
        # O NOVO BOTÃO FANTASMA
        self.btn_toggle_ghost = QPushButton("✏️ Travar/Modo Fantasma")
        self.btn_toggle_ghost.setStyleSheet("background-color: #27ae60;")
        
        h_set = QHBoxLayout()
        self.ipt_fonte = QLineEdit(str(self.manager.overlay_font_size))
        self.btn_salvar_config = QPushButton("Save Config")
        h_set.addWidget(QLabel("Font Size:"))
        h_set.addWidget(self.ipt_fonte)
        h_set.addWidget(self.btn_salvar_config)
        
        set_layout.addWidget(lbl_set)
        set_layout.addWidget(self.btn_toggle_ghost)
        set_layout.addLayout(h_set)
        layout.addWidget(settings_frame)

        # Conexões
        self.btn_listen.clicked.connect(self.action_listen)
        self.btn_stop.clicked.connect(self.action_stop)
        self.btn_pause.clicked.connect(self.action_pause)
        self.cb_lang.currentTextChanged.connect(self.action_change_lang)
        self.btn_buscar.clicked.connect(self.action_buscar_manual)
        self.btn_salvar_config.clicked.connect(self.action_salvar_config)
        self.btn_toggle_ghost.clicked.connect(self.action_toggle_ghost)
        self.btn_manual_sync.clicked.connect(self.action_mostrar_lista_sinc)
        self.list_letras.itemClicked.connect(self.action_aplicar_sinc)

        self.timer = QTimer()
        self.timer.timeout.connect(self.update_ui_loop)
        self.timer.start(500)

    def closeEvent(self, event):
        if self.overlay_process:
            try:
                self.overlay_process.terminate()
            except Exception:
                pass
        event.accept()


    def action_toggle_ghost(self):
        self.manager.modo_fantasma = not self.manager.modo_fantasma
        if self.manager.modo_fantasma:
            self.btn_toggle_ghost.setText("👻 Destravar/Modo Edição")
            self.btn_toggle_ghost.setStyleSheet("background-color: #555;")
        else:
            self.btn_toggle_ghost.setText("✏️ Travar/Modo Fantasma")
            self.btn_toggle_ghost.setStyleSheet("background-color: #27ae60;")

    def action_listen(self):
        self.manager.reset_state()
        self.manager.escutando = True
        self.manager.status_busca = "Listening..."

    def action_stop(self):
        self.manager.reset_state()
        self.lbl_musica.setText("Stopped")
        self.lbl_artista.setText("---")
        self.btn_pause.hide()
        self.cb_lang.hide()
        self.btn_manual_sync.hide()
        self.list_letras.hide()

    def action_pause(self):
        if not self.manager.letra_sincronizada: return
        if self.manager.letra_pausada:
            self.manager.tempo_referencia_sistema += (time.time() - self.manager.momento_pausa)
            self.manager.letra_pausada = False
            self.btn_pause.setText("⏸️ Pause")
            self.btn_pause.setStyleSheet("")
        else:
            self.manager.letra_pausada = True
            self.manager.momento_pausa = time.time()
            self.btn_pause.setText("▶️ Play")
            self.btn_pause.setStyleSheet("background-color: #a08d4c; color: #111;")

    def action_change_lang(self, text):
        mapa = {"🌐 Original": "original", "🇧🇷 Pt-Br": "pt", "🇪🇸 Español": "es", "🇺🇸 English": "en"}
        lang = mapa.get(text, "original")
        if lang == "original":
            self.manager.letra_sincronizada = self.manager.letra_original
        else:
            if self.manager.gerar_traducao(lang):
                self.manager.letra_sincronizada = self.manager.traducoes_cacheadas[lang]

    def action_buscar_manual(self):
        art, mus = self.ipt_artista.text(), self.ipt_musica.text()
        if not art or not mus: return
        self.lbl_artista.setText("Searching...")
        def worker():
            letra = self.manager.buscar_letra_lrclib(art, mus)
            self.manager.busca_concluida = True
            if letra:
                self.manager.letra_original = self.manager.letra_sincronizada = letra
                self.manager.musica_atual, self.manager.artista_atual = mus, art
                self.manager.escutando = True  
                self.manager.tempo_referencia_sistema = time.time()
                self.manager.status_busca = "Listening..."
            else:
                self.manager.status_busca = "Lyrics not found!"
        threading.Thread(target=worker, daemon=True).start()

    def action_salvar_config(self):
        try: self.manager.overlay_font_size = int(self.ipt_fonte.text())
        except ValueError: pass
        self.btn_salvar_config.setText("Saved ✔️")
        QTimer.singleShot(2000, lambda: self.btn_salvar_config.setText("Save Config"))

    def action_mostrar_lista_sinc(self):
        if self.list_letras.isVisible():
            self.list_letras.hide()
            return
        self.list_letras.clear()
        for i, item in enumerate(self.manager.letra_sincronizada):
            list_item = QListWidgetItem(item['letra'])
            list_item.setData(Qt.ItemDataRole.UserRole, item['tempo'])
            self.list_letras.addItem(list_item)
        self.list_letras.show()

    def action_aplicar_sinc(self, item):
        tempo = item.data(Qt.ItemDataRole.UserRole)
        self.manager.tempo_referencia_sistema = time.time() - tempo
        self.manager.delay_manual, self.manager.momento_pausa = 0.0, 0.0
        self.manager.letra_pausada = False
        self.btn_pause.setText("⏸️ Pause")
        self.btn_pause.setStyleSheet("")
        self.list_letras.hide()

    def update_ui_loop(self):
        # Atualiza a interface PyQt (o WebSocket se vira sozinho em segundo plano)
        self.lbl_musica.setText(self.manager.musica_atual or "Identifying...")
        if not self.manager.musica_atual and not self.manager.busca_concluida:
            self.lbl_artista.setText(self.manager.status_busca)
        else:
            self.lbl_artista.setText(self.manager.artista_atual or "---")

        if self.manager.musica_atual and self.manager.letra_sincronizada:
            self.btn_manual_sync.show()
            self.btn_pause.show()
            self.cb_lang.show()

def encontrar_porta_livre():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(('', 0))
        return s.getsockname()[1]

if __name__ == "__main__":
    app = QApplication(sys.argv)
    
    porta_disponivel = encontrar_porta_livre()
    log(f"Servidor iniciado na porta dinâmica: {porta_disponivel}", "SYSTEM")
    
    threading.Thread(target=start_background_loop, args=(porta_disponivel,), daemon=True).start()
    
    processo_overlay = None
    try:
        processo_overlay = subprocess.Popen(["FrontLineOverlay.exe", str(porta_disponivel)])
    except FileNotFoundError:
        log("Aviso: FrontLineOverlay.exe não encontrado.", "SYSTEM")

    window = ControlWindow(manager, overlay_process=processo_overlay)
    window.show()
    
    sys.exit(app.exec())