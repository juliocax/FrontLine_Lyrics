import sys
import os
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
import socket

import pyaudiowpatch as pyaudio
from shazamio import Shazam
from deep_translator import GoogleTranslator

from PyQt6.QtWidgets import (QApplication, QWidget, QVBoxLayout, QHBoxLayout, 
                             QLabel, QPushButton, QLineEdit, QComboBox, 
                             QListWidget, QListWidgetItem, QFrame, QSlider,
                             QSizePolicy, QSizePolicy)
from PyQt6.QtCore import Qt, QTimer, pyqtSignal, QObject
from PyQt6.QtGui import QFont, QIcon, QPixmap, QImage, QAction, QColor

# --- ESCUDO CONTRA CRASH SILENCIOSO ---
def controle_de_erros(exctype, value, tb):
    print("=== ERRO CRÍTICO ENCONTRADO ===")
    traceback.print_exception(exctype, value, tb)
sys.excepthook = controle_de_erros

def log(mensagem, categoria="SYSTEM"):
    timestamp = time.strftime("%H:%M:%S")
    print(f"[{timestamp}] [{categoria}] {mensagem}")

# Sinais para atualizar a UI a partir de outras Threads
class Signaler(QObject):
    update_cover = pyqtSignal(bytes)
    song_finished = pyqtSignal()
    search_error = pyqtSignal(str)

ui_signals = Signaler()

class MusicManager:
    def __init__(self):
        self.shazam = Shazam()
        self.session_id = time.time()
        self.servidor_rodando = True   
        self.pyaudio_instance = pyaudio.PyAudio()
        self.device_info = self._configurar_loopback()
        
        # Variáveis controladas pelo Painel
        self.overlay_font_size = 26
        self.modo_fantasma = False
        self.auto_sync_ativado = False
        self.capa_atual_bytes = None
        
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
        except Exception: return None

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
        self.capa_atual_bytes = None
        ui_signals.update_cover.emit(b'')

    async def reconhecer_snippet(self, audio_bytes):
        try:
            resultado = await self.shazam.recognize(audio_bytes)
            if resultado and 'track' in resultado:
                track = resultado['track']
                cover = track.get('images', {}).get('coverart', '')
                return track['title'], track['subtitle'], resultado.get('matches', [{}])[0].get('offset', 0.0), cover
        except Exception: pass
        return None, None, 0.0, ""

    def buscar_letra_lrclib(self, artista, musica):
        headers = {"User-Agent": "FrontLineLyricsApp/3.0"}
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
        
        buscas = [{"track_name": musica_limpa, "artist_name": artista_limpo}, f"{musica_limpa} {artista_limpo}", musica_limpa]

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
                    for item in r.json():
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
        
        if not self.escutando or (self.escutando and not self.musica_atual):
            overlay_atual = "Waiting for the next song..."
        elif self.musica_atual and not self.busca_concluida:
            overlay_atual = f"Synchronizing lyrics for '{self.musica_atual}'..."
        elif self.busca_concluida and not self.letra_sincronizada:
            overlay_atual = "Synced lyrics not available."
        elif self.letra_sincronizada:
            tempo_base = self.momento_pausa if self.letra_pausada else time.time()
            tempo_decorrido = (tempo_base - self.tempo_referencia_sistema) + self.delay_manual
            
            if self.auto_sync_ativado and tempo_decorrido > self.letra_sincronizada[-1]['tempo'] + 2.0:
                ui_signals.song_finished.emit()
            
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
    while manager.servidor_rodando:
        if not manager.escutando or manager.busca_concluida:
            tempo_gravacao_atual = 4 
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
        
        nova_musica, novo_artista, offset_shazam, url_capa = await manager.reconhecer_snippet(audio_bytes)
        
        if nova_musica and manager.escutando:
            manager.musica_atual, manager.artista_atual = nova_musica, novo_artista
            manager.status_busca = "Fetching lyrics..."
            tempo_gravacao_atual = 4
            
            if url_capa:
                try:
                    res = requests.get(url_capa, timeout=3)
                    if res.status_code == 200:
                        manager.capa_atual_bytes = res.content
                        ui_signals.update_cover.emit(res.content)
                except Exception: pass

            letra = await loop.run_in_executor(None, manager.buscar_letra_lrclib, novo_artista, nova_musica)
            manager.busca_concluida = True
            manager.status_busca = "Listening..."
            if letra:
                manager.letra_original = manager.letra_sincronizada = letra
                manager.traducoes_cacheadas = {} 
                manager.idioma_atual = "original"
                manager.tempo_referencia_sistema = t_inicio_gravacao - offset_shazam
        else:
            manager.status_busca = "Analyzing audio..."
        await asyncio.sleep(2)

clientes_conectados = set()

async def ws_handler(websocket):
    clientes_conectados.add(websocket)
    try: await websocket.wait_closed()
    finally: clientes_conectados.remove(websocket)

async def broadcast_estado_ui(manager):
    while manager.servidor_rodando:
        if clientes_conectados:
            mensagem = json.dumps(manager.obter_estado_atual())
            websockets.broadcast(clientes_conectados, mensagem)
        await asyncio.sleep(0.1)

async def main_background(manager, porta):
    asyncio.create_task(async_worker_verificacao(manager))
    asyncio.create_task(broadcast_estado_ui(manager))
    async with websockets.serve(ws_handler, "localhost", porta):
        await asyncio.Future()

def start_background_loop(porta):
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.run_until_complete(main_background(manager, porta))

# ==========================================
# PAINEL DE CONTROLE (DEEP STAGE / GLASS UI)
# ==========================================
# Mudança Principal: rgba(255, 255, 255, 0.05) e bordas finas para simular vidro.
# Gradiente radial aplicado diretamente no QWidget principal.
STYLESHEET = """
QWidget#Main { 
    background-color: qradialgradient(spread:pad, cx:0.5, cy:0.1, radius:1, fx:0.5, fy:0.1, stop:0 #1a0b2e, stop:1 #020202);
    color: #f0f0f0; 
    font-family: 'Segoe UI', sans-serif; 
}
QFrame#GlassCard { 
    background-color: rgba(255, 255, 255, 0.05); 
    border-radius: 12px; 
    border: 1px solid rgba(255, 255, 255, 0.1); 
}
QLabel { background: transparent; }
QLabel#NowPlaying { color: #888; font-size: 10px; font-weight: bold; letter-spacing: 2px; text-transform: uppercase; }
QLabel#SongTitle { font-size: 18px; font-weight: bold; color: white; }
QLabel#ArtistName { color: #a955ff; font-size: 13px; }
QLabel#LiveDot { color: #1ed760; font-size: 20px; font-weight: bold; }
QLabel#SettingsHeader { color: rgba(255, 255, 255, 0.5); font-size: 10px; font-weight: bold; letter-spacing: 1px; }

QPushButton { 
    background-color: rgba(255, 255, 255, 0.1); 
    border: 1px solid rgba(255, 255, 255, 0.05); 
    border-radius: 6px; 
    padding: 10px; 
    font-weight: bold; 
    font-size: 11px; 
    text-transform: uppercase;
    color: white;
}
QPushButton:hover { background-color: rgba(255, 255, 255, 0.15); }
QPushButton:disabled { color: rgba(255, 255, 255, 0.2); background-color: rgba(0,0,0,0.2); border: 1px solid rgba(255,255,255,0.02); }

QPushButton#BtnListen { 
    background-color: #6A0DAD; 
    font-size: 13px; 
    color: white; 
    border: none; 
    letter-spacing: 1px;
}
QPushButton#BtnListen:hover { background-color: #8A2BE2; }
QPushButton#BtnListenActive { background-color: #1ed760; font-size: 13px; color: black; border: none; }

QPushButton#SettingsToggle { 
    background-color: transparent; 
    border: none; 
    color: rgba(255, 255, 255, 0.7); 
    text-transform: uppercase; 
    font-size: 11px;
    letter-spacing: 1px;
}
QPushButton#SettingsToggle:hover { color: white; }

QLineEdit, QComboBox, QListWidget { 
    background-color: rgba(0, 0, 0, 0.3); 
    border: 1px solid rgba(255, 255, 255, 0.1); 
    border-radius: 6px; 
    padding: 8px; 
    color: white; 
}
QComboBox QAbstractItemView { background-color: #0b0510; color: white; border: 1px solid #321659; selection-background-color: #5e17eb; }

QSlider::groove:horizontal { border-radius: 4px; height: 6px; background-color: rgba(255, 255, 255, 0.1); }
QSlider::handle:horizontal { background-color: #8A2BE2; border: none; height: 16px; width: 16px; margin: -5px 0; border-radius: 8px; }
QSlider::handle:horizontal:hover { background-color: #a955ff; }

/* Switch estilizado para o Ghost Mode (CheckBox) */
QCheckBox#GhostSwitch { color: rgba(255, 255, 255, 0.7); font-size: 11px; text-transform: uppercase; font-weight: bold; }
QCheckBox#GhostSwitch::indicator { width: 40px; height: 20px; }
QCheckBox#GhostSwitch::indicator:unchecked { image: url(assets/switch_off.png); } /* Precisa criar essa imagem ou usar desenho */
QCheckBox#GhostSwitch::indicator:checked { image: url(assets/switch_on.png); }
"""

class ControlWindow(QWidget):
    def __init__(self, manager, porta_servidor):
        super().__init__()
        self.manager = manager
        self.porta_servidor = porta_servidor
        self.overlay_process = None
        
        self.setObjectName("Main")
        self.setWindowTitle("FrontLine Deck")
        self.setStyleSheet(STYLESHEET)
        
        # Define Tamanhos Mínimos e Máximos
        self.setMinimumSize(360, 600)
        self.setMaximumSize(400, 850)
        self.resize(370, 720)
        
        # Desativa Maximizar
        self.setWindowFlags(Qt.WindowType.Window | Qt.WindowType.WindowMinimizeButtonHint | Qt.WindowType.WindowCloseButtonHint)
        
        # Configura Ícone da Janela
        caminho_ico = os.path.join("assets", "logo.ico")
        if os.path.exists(caminho_ico):
            self.setWindowIcon(QIcon(caminho_ico))

        self.main_layout = QVBoxLayout(self)
        self.main_layout.setContentsMargins(15, 15, 15, 15)
        self.main_layout.setSpacing(15)

        # ZONA 1: HEADER E DISPLAY DO PALCO
        self.header_frame = QFrame()
        self.header_frame.setObjectName("GlassCard")
        header_layout = QVBoxLayout(self.header_frame)
        header_layout.setContentsMargins(15, 10, 15, 15)
        header_layout.setSpacing(5)
        
        top_bar = QHBoxLayout()
        lbl_np = QLabel("NOW PLAYING")
        lbl_np.setObjectName("NowPlaying")
        self.lbl_live_dot = QLabel("●")
        self.lbl_live_dot.setObjectName("LiveDot")
        self.lbl_live_dot.hide() # Escondido até sincar
        top_bar.addWidget(lbl_np)
        top_bar.addStretch()
        top_bar.addWidget(self.lbl_live_dot)
        header_layout.addLayout(top_bar)

        self.lbl_musica = QLabel("Deck Ready")
        self.lbl_musica.setObjectName("SongTitle")
        self.lbl_musica.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_musica.setWordWrap(True)
        
        self.lbl_artista = QLabel("Press Listen to start")
        self.lbl_artista.setObjectName("ArtistName")
        self.lbl_artista.setAlignment(Qt.AlignmentFlag.AlignCenter)
        
        header_layout.addWidget(self.lbl_musica)
        header_layout.addWidget(self.lbl_artista)
        
        # Idioma Visível (Movido para o topo conforme mock-up)
        self.cb_lang = QComboBox()
        self.cb_lang.addItems(["🌐 Original", "🇧🇷 Pt-Br", "🇪🇸 Español", "🇺🇸 English"])
        self.cb_lang.setToolTip("Overlay Language")
        header_layout.addWidget(self.cb_lang)
        
        self.main_layout.addWidget(self.header_frame)

        # ZONA 2: CAPA E CONTROLES CENTRAIS
        middle_layout = QVBoxLayout()
        middle_layout.setSpacing(15)
        
        self.lbl_capa = QLabel()
        self.lbl_capa.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_capa.setFixedSize(160, 160)
        self.lbl_capa.setStyleSheet("background-color: rgba(255,255,255,0.02); border-radius: 8px; border: 1px solid rgba(255,255,255,0.05);")
        
        capa_container = QHBoxLayout()
        capa_container.addStretch()
        capa_container.addWidget(self.lbl_capa)
        capa_container.addStretch()
        middle_layout.addLayout(capa_container)

        # Botões de Ação Principais
        main_btns = QHBoxLayout()
        main_btns.setSpacing(10)
        
        # Botão Listen (Destaque Central)
        self.btn_listen = QPushButton("LISTEN / AUTO-SYNC")
        self.btn_listen.setObjectName("BtnListen")
        self.btn_listen.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        
        # Botões Secundários
        self.btn_pause = QPushButton("> / ||") # Play/Pause Símbolo
        self.btn_pause.setToolTip("Play/Pause")
        self.btn_pause.setDisabled(True)
        
        self.btn_stop = QPushButton("RESET DECK") # Trash/Clear Símbolo (Texto por enquanto)
        self.btn_stop.setToolTip("Clear Session")
        
        main_btns.addWidget(self.btn_pause)
        main_btns.addWidget(self.btn_listen, 3) # Peso maior para o central
        main_btns.addWidget(self.btn_stop)
        middle_layout.addLayout(main_btns)
        
        self.main_layout.addLayout(middle_layout)
        self.main_layout.addStretch() # Empurra configurações para o fundo

        # ZONA 3: BASTIDORES (CONFIGURAÇÕES RETRÁTEIS)
        self.backstage_frame = QFrame()
        self.backstage_frame.setObjectName("GlassCard")
        self.set_layout = QVBoxLayout(self.backstage_frame)
        self.set_layout.setContentsMargins(15, 5, 15, 15)
        self.set_layout.setSpacing(10)
        
        # Botão Toggle para abrir/fechar
        self.btn_toggle_settings = QPushButton("BACKSTAGE / SETTINGS ⚙")
        self.btn_toggle_settings.setObjectName("SettingsToggle")
        self.set_layout.addWidget(self.btn_toggle_settings)
        
        # Container para o conteúdo (que vai sumir/aparecer)
        self.settings_content = QWidget()
        self.settings_content_layout = QVBoxLayout(self.settings_content)
        self.settings_content_layout.setContentsMargins(0, 5, 0, 0)
        self.settings_content_layout.setSpacing(12)
        
        # --- Pesquisa Manual (Reintroduzida) ---
        lbl_manual = QLabel("MANUAL SEARCH")
        lbl_manual.setObjectName("SettingsHeader")
        self.settings_content_layout.addWidget(lbl_manual)
        
        h_manual_inputs = QHBoxLayout()
        self.ipt_artista = QLineEdit()
        self.ipt_artista.setPlaceholderText("Artist")
        self.ipt_musica = QLineEdit()
        self.ipt_musica.setPlaceholderText("Song")
        h_manual_inputs.addWidget(self.ipt_artista)
        h_manual_inputs.addWidget(self.ipt_musica)
        self.settings_content_layout.addLayout(h_manual_inputs)
        
        self.btn_buscar = QPushButton("SEARCH AND SYNC")
        self.settings_content_layout.addWidget(self.btn_buscar)
        
        frame_sep = QFrame() # Separador visual
        frame_sep.setFrameShape(QFrame.FrameShape.HLine)
        frame_sep.setStyleSheet("color: rgba(255,255,255,0.05);")
        self.settings_content_layout.addWidget(frame_sep)

        lbl_ov_set = QLabel("OVERLAY CONTROLS")
        lbl_ov_set.setObjectName("SettingsHeader")
        self.settings_content_layout.addWidget(lbl_ov_set)

        # Slider de Fonte
        h_font = QHBoxLayout()
        self.lbl_font_val = QLabel(f"Font: {self.manager.overlay_font_size}px")
        self.lbl_font_val.setStyleSheet("color: rgba(255,255,255,0.7); font-size: 11px;")
        self.slider_fonte = QSlider(Qt.Orientation.Horizontal)
        self.slider_fonte.setRange(14, 60)
        self.slider_fonte.setValue(self.manager.overlay_font_size)
        h_font.addWidget(self.lbl_font_val)
        h_font.addWidget(self.slider_fonte)
        self.settings_content_layout.addWidget(h_font)
        
        # Ghost Mode e Reload
        h_ghost = QHBoxLayout()
        self.cb_ghost = QCheckBox("LOCK OVERLAY (GHOST MODE)")
        self.cb_ghost.setObjectName("GhostSwitch")
        # Nota: Idealmente usar imagens Assets/switch_on.png e Assets/switch_off.png no QSS
        
        self.btn_reload = QPushButton("RELOAD OVERLAY") # Refresh Símbolo
        self.btn_reload.setToolTip("Restart Overlay App")
        h_ghost.addWidget(self.cb_ghost)
        h_ghost.addStretch()
        h_ghost.addWidget(self.btn_reload)
        self.settings_content_layout.addWidget(h_ghost)

        self.set_layout.addWidget(self.settings_content)
        self.main_layout.addWidget(self.backstage_frame)

        # Lista Manual (Para Sincronismo)
        self.list_letras = QListWidget()
        self.list_letras.hide()
        self.main_layout.addWidget(self.list_letras)

        # Começa fechada
        self.settings_content.hide()

        # Conexões
        self.btn_listen.clicked.connect(self.action_listen)
        self.btn_stop.clicked.connect(self.action_stop)
        self.btn_pause.clicked.connect(self.action_pause)
        self.cb_lang.currentTextChanged.connect(self.action_change_lang)
        self.btn_toggle_settings.clicked.connect(self.toggle_settings_panel)
        self.btn_buscar.clicked.connect(self.action_buscar_manual)
        self.slider_fonte.valueChanged.connect(self.action_mudar_fonte)
        self.cb_ghost.toggled.connect(self.action_toggle_ghost)
        self.btn_reload.clicked.connect(self.iniciar_subprocesso_overlay)
        self.list_letras.itemClicked.connect(self.action_aplicar_sinc)

        # Sinais de Threads
        ui_signals.update_cover.connect(self.atualizar_capa_ui)
        ui_signals.song_finished.connect(self.action_song_finished)
        ui_signals.search_error.connect(self.mostrar_erro_busca)

        # Inicia o Overlay
        self.iniciar_subprocesso_overlay()

        self.timer = QTimer()
        self.timer.timeout.connect(self.update_ui_loop)
        self.timer.start(500)

    # --- Lógica da UI Retrátil ---
    def toggle_settings_panel(self):
        if self.settings_content.isVisible():
            self.settings_content.hide()
            self.btn_toggle_settings.setText("BACKSTAGE / SETTINGS ⚙")
        else:
            self.settings_content.show()
            self.btn_toggle_settings.setText("HIDE SETTINGS ▲")

    # --- Lógica do Ciclo de Vida do Overlay ---
    def iniciar_subprocesso_overlay(self):
        if self.overlay_process:
            try: self.overlay_process.terminate()
            except Exception: pass
            
        if getattr(sys, 'frozen', False):
            diretorio_base = os.path.dirname(sys.executable)
        else:
            diretorio_base = os.path.dirname(os.path.abspath(__file__))
            
        caminho_overlay = os.path.join(diretorio_base, "FrontLineOverlay.exe")
        try:
            self.overlay_process = subprocess.Popen([caminho_overlay, str(self.porta_servidor)])
        except FileNotFoundError:
            log(f"Aviso: Overlay não encontrado em {caminho_overlay}", "SYSTEM")

    # Modificado: Fecha tudo ao clicar no X
    def closeEvent(self, event):
        if self.overlay_process:
            try: self.overlay_process.terminate()
            except Exception: pass
        QApplication.quit()
        event.accept()

    def atualizar_capa_ui(self, image_bytes):
        if not image_bytes:
            self.lbl_capa.clear()
            self.lbl_capa.setText("Cover")
            self.lbl_capa.setStyleSheet("background-color: rgba(255,255,255,0.02); border-radius: 8px; border: 1px solid rgba(255,255,255,0.05); color: rgba(255,255,255,0.2); font-size: 10px; font-weight: bold; text-transform: uppercase; letter-spacing: 1px;")
            return
        img = QImage.fromData(image_bytes)
        pixmap = QPixmap.fromImage(img).scaled(160, 160, Qt.AspectRatioMode.KeepAspectRatioByExpanding, Qt.TransformationMode.SmoothTransformation)
        self.lbl_capa.setPixmap(pixmap)
        self.lbl_capa.setStyleSheet("border-radius: 8px; border: 1px solid rgba(255,255,255,0.1);") # Borda mais visível com capa

    # --- Ações dos Controles ---
    def action_toggle_autosync(self, checked):
        # Nota: O botão LISTEN central agora acumula a função de Auto-Sync.
        # Ativaremos Auto-Sync sempre que clicar em Listen.
        pass

    def action_song_finished(self):
        # Gatilho chamado quando a música acaba (Auto-Sync)
        self.action_listen()

    def action_toggle_ghost(self, checked):
        self.manager.modo_fantasma = checked

    def action_mudar_fonte(self, value):
        self.manager.overlay_font_size = value
        self.lbl_font_val.setText(f"Font: {value}px")

    def action_listen(self):
        self.manager.reset_state()
        self.manager.escutando = True
        self.manager.auto_sync_ativado = True # Ativa Auto-Sync por padrão ao ouvir
        self.manager.status_busca = "Listening..."
        self.lbl_live_dot.hide()
        
        self.btn_listen.setText("LISTENING...")
        self.btn_listen.setObjectName("BtnListenActive")
        self.setStyleSheet(self.styleSheet()) # Força atualização visual
        self.cb_lang.setCurrentIndex(0) # Reseta o idioma

    def action_stop(self):
        self.manager.reset_state()
        self.lbl_musica.setText("Deck Ready")
        self.lbl_artista.setText("---")
        self.lbl_live_dot.hide()
        self.btn_pause.setDisabled(True)
        self.btn_listen.setText("LISTEN / AUTO-SYNC")
        self.btn_listen.setObjectName("BtnListen")
        self.setStyleSheet(self.styleSheet())
        self.list_letras.hide()
        self.manager.auto_sync_ativado = False

    def action_pause(self):
        if not self.manager.letra_sincronizada: return
        if self.manager.letra_pausada:
            self.manager.tempo_referencia_sistema += (time.time() - self.manager.momento_pausa)
            self.manager.letra_pausada = False
            self.btn_pause.setText("> / ||")
            self.btn_pause.setStyleSheet("")
        else:
            self.manager.letra_pausada = True
            self.manager.momento_pausa = time.time()
            self.btn_pause.setText("> / ||")
            # Destaque suave de pause (cor Midnight)
            self.btn_pause.setStyleSheet("background-color: #3b1863; color: white;")

    def action_change_lang(self, text):
        mapa = {"🌐 Original": "original", "🇧🇷 Pt-Br": "pt", "🇪🇸 Español": "es", "🇺🇸 English": "en"}
        lang = mapa.get(text, "original")
        if lang == "original":
            self.manager.letra_sincronizada = self.manager.letra_original
        else:
            if self.manager.gerar_traducao(lang):
                self.manager.letra_sincronizada = self.manager.traducoes_cacheadas[lang]

    # Lógica de Pesquisa Manual
    def action_buscar_manual(self):
        art, mus = self.ipt_artista.text(), self.ipt_musica.text()
        if not art or not mus: return
        
        self.manager.reset_state()
        self.btn_buscar.setText("SEARCHING...")
        self.btn_buscar.setDisabled(True)
        self.lbl_musica.setText("Searching Manual...")
        self.lbl_artista.setText(f"'{mus}' by '{art}'")
        
        def worker():
            letra = self.manager.buscar_letra_lrclib(art, mus)
            self.manager.busca_concluida = True
            if letra:
                self.manager.letra_original = self.manager.letra_sincronizada = letra
                self.manager.musica_atual, self.manager.artista_atual = mus, art
                self.manager.escutando = True  
                self.manager.tempo_referencia_sistema = time.time()
                log(f"Letra encontrada manualmente: {mus}")
            else:
                ui_signals.search_error.emit("Lyrics not found!")
                log(f"Letra manual não encontrada: {mus}")
                
            # Restaura botão na UI principal
            self.btn_buscar.setText("SEARCH AND SYNC")
            self.btn_buscar.setDisabled(False)

        threading.Thread(target=worker, daemon=True).start()

    def mostrar_erro_busca(self, mensagem):
        self.lbl_musica.setText("---")
        self.lbl_artista.setText(mensagem)

    def action_aplicar_sinc(self, item):
        tempo = item.data(Qt.ItemDataRole.UserRole)
        self.manager.tempo_referencia_sistema = time.time() - tempo
        self.manager.delay_manual, self.manager.momento_pausa = 0.0, 0.0
        self.manager.letra_pausada = False
        self.btn_pause.setText("> / ||")
        self.btn_pause.setStyleSheet("")
        self.list_letras.hide()

    # --- Loop de Atualização da UI (Status) ---
    def update_ui_loop(self):
        # Atualiza apenas status e títulos. Letras vão pro Overlay.
        if self.manager.musica_atual:
            self.lbl_musica.setText(self.manager.musica_atual)
            self.lbl_artista.setText(self.manager.artista_atual or "---")
        
        # Gerencia Bolinha Verde de Sinc
        if self.manager.escutando and self.manager.busca_concluida and self.manager.letra_sincronizada:
            self.lbl_live_dot.show()
            self.btn_pause.setDisabled(False)
            if not self.manager.letra_pausada:
                 self.btn_listen.setText("SYNCED")
                 self.btn_listen.setObjectName("BtnListen")
                 self.setStyleSheet(self.styleSheet())
        else:
            self.lbl_live_dot.hide()

def encontrar_porta_livre():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(('', 0))
        return s.getsockname()[1]

if __name__ == "__main__":
    app = QApplication(sys.argv)
    
    # Fundamental para fechar o processo ao fechar a janela
    app.setQuitOnLastWindowClosed(True)
    
    porta_disponivel = encontrar_porta_livre()
    log(f"Stage Server started on port: {porta_disponivel}", "SYSTEM")
    
    threading.Thread(target=start_background_loop, args=(porta_disponivel,), daemon=True).start()
    
    window = ControlWindow(manager, porta_disponivel)
    window.show()
    
    sys.exit(app.exec())