if (document.getElementById('frontline-lyrics-root')) {
    console.log("FrontLine Lyrics is already running on this tab.");
} else {
    function apiFetch(endpoint) {
        return new Promise((resolve, reject) => {
            chrome.runtime.sendMessage({ action: "api_call", endpoint: endpoint }, (response) => {
                if (chrome.runtime.lastError) return reject(chrome.runtime.lastError);
                if (response && response.success) resolve(response.data);
                else reject(new Error(response?.erro || "Connection error"));
            });
        });
    }

    const host = document.createElement('div');
    host.id = 'frontline-lyrics-root';
    document.body.appendChild(host);
    
    const shadow = host.attachShadow({ mode: 'closed' });

    const panelHTML = `
    <div id="lsp-panel-container">
        <style>
            #lsp-panel-container {
                position: fixed; top: 20px; right: 20px; z-index: 2147483647; 
                width: 320px; background-color: #1a1a1a; color: #e0e0e0;
                border-radius: 8px; box-shadow: 0 10px 30px rgba(0,0,0,0.8);
                font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; 
                padding: 15px; display: block; border: 1px solid #444;
                user-select: none;
            }
            #lsp-panel-container * { box-sizing: border-box; }
            .lsp-header { 
                display: flex; justify-content: space-between; align-items: center; 
                border-bottom: 1px solid #444; padding-bottom: 8px; cursor: move; 
            }
            .lsp-header h2 { font-size: 12px; text-transform: uppercase; color: #888; margin: 0; letter-spacing: 1px; }
            
            .lsp-music-info { background: #2d2d2d; padding: 10px; border-radius: 6px; border: 1px solid #444; margin-top: 12px; }
            #lsp-musica { font-weight: bold; font-size: 16px; margin-bottom: 2px; color: #fff; }
            #lsp-artista { font-size: 14px; color: #888; }
            
            .lsp-controls-row { display: flex; gap: 8px; margin-top: 10px; flex-wrap: wrap; }
            #lsp-panel-container button {
                flex: 1; background: #2d2d2d; color: #e0e0e0; border: 1px solid #444; 
                padding: 8px; cursor: pointer; border-radius: 4px; font-size: 11px; 
                font-weight: bold; text-transform: uppercase; transition: 0.2s;
            }
            #lsp-panel-container button:hover { background: #3d3d3d; border-color: #555; }
            
            #lsp-btnSelecionarLinha { display: none; width: 100%; margin-top: 8px; }
            
            #lsp-painelManual { border-top: 1px solid #444; padding-top: 10px; display: none; flex-direction: column; gap: 8px; margin-top: 10px; }
            #lsp-painelManual input { background: #111; border: 1px solid #444; color: #e0e0e0; padding: 8px; border-radius: 4px; font-size: 13px; outline: none; }
            #lsp-painelManual input:focus { border-color: #444; background: #1a1a1a; }
            
            #lsp-listaLetraCompleta { max-height: 150px; overflow-y: auto; background: #111; border: 1px solid #444; border-radius: 4px; display: none; font-size: 12px; padding: 5px; margin-top: 10px; }
            .lsp-linha-clicavel { padding: 6px; cursor: pointer; color: #888; border-bottom: 1px solid #222; }
            .lsp-linha-clicavel:hover { background: #222; color: #fff; }
            
            #lsp-status { font-size: 10px; color: #888; text-align: center; margin-top: 10px; }
            .lsp-aviso-privacidade { font-size: 9px; color: #cc8800; text-align: center; margin-top: 6px; line-height: 1.2; }

            .lsp-btn-fechar {
                background: none !important; border: none !important; color: #888 !important;
                font-size: 18px !important; cursor: pointer; padding: 0 5px !important;
                line-height: 1; transition: color 0.2s;
            }
            .lsp-btn-fechar:hover { color: #fff !important; }
            
            #lsp-btnReconectar { display: none; padding: 4px 8px !important; font-size: 10px !important; margin-right: 5px; }

            /* Estilos do Modal de Privacidade */
            #lsp-privacy-modal {
                display: none; position: absolute; top: 0; left: 0; width: 100%; height: 100%;
                background: rgba(26, 26, 26, 0.95); z-index: 100; border-radius: 8px;
                flex-direction: column; justify-content: center; align-items: center;
                padding: 15px; text-align: center; box-sizing: border-box;
                backdrop-filter: blur(4px);
            }
            #lsp-privacy-modal h3 { color: #e74c3c; margin: 0 0 10px 0; font-size: 13px; text-transform: uppercase; letter-spacing: 0.5px;}
            #lsp-privacy-modal p { font-size: 11px; color: #ccc; margin-bottom: 10px; line-height: 1.4; text-align: left; }
            .modal-buttons { display: flex; gap: 8px; width: 100%; margin-top: 10px; }
            .btn-accept { background: #27ae60 !important; color: white !important; }
            .btn-accept:hover { background: #2ecc71 !important; }
            .btn-reject { background: #c0392b !important; color: white !important; }
            .btn-reject:hover { background: #e74c3c !important; }

            #lsp-overlay {
                position: fixed; bottom: 80px; left: 50%; transform: translateX(-50%);
                z-index: 2147483646; background: rgba(0,0,0,0.85); color: white;
                border-radius: 10px; text-align: center;
                cursor: grab; user-select: none;
                width: 450px; height: 160px; 
                resize: both; overflow: hidden; 
                display: flex; flex-direction: column; justify-content: center; align-items: center;
                padding: 10px; box-sizing: border-box;
            }
        </style>
        
        <div class="lsp-header" id="lsp-drag-handle">
            <h2>FrontLine Lyrics</h2>
            <div style="display: flex; align-items: center; gap: 8px;">
                <button id="lsp-btnReconectar">Retry Connection</button>
                <div id="lsp-status-icon" style="color: #a08d4c; font-size: 14px;">●</div>
                <button id="lsp-fechar-extensao" class="lsp-btn-fechar" title="Close extension">&times;</button>
            </div>
        </div>

        <div class="lsp-music-info">
            <div id="lsp-musica">Waiting...</div>
            <div id="lsp-artista">---</div>
        </div>

        <div class="lsp-controls-row">
            <button id="lsp-btnIniciar">Listen</button>
            <button id="lsp-btnParar">Stop</button>
            <button id="lsp-btnManual">Search Lyrics</button>
        </div>

        <button id="lsp-btnSelecionarLinha">Manual Sync</button>
        <div id="lsp-listaLetraCompleta"></div>

        <div id="lsp-painelManual">
            <input type="text" id="lsp-iptArtista" placeholder="Artist">
            <input type="text" id="lsp-iptMusica" placeholder="Song">
            <button id="lsp-btnBuscarManual">Search</button>
        </div>
        
        <div id="lsp-status">Alt + M to hide</div>
        

        <div id="lsp-privacy-modal">
            <h3>About Audio Capture</h3>
            <p>
                To sync lyrics, "Listen" mode needs to temporarily capture your system audio.
            </p>
            <p>
                Your voice and calls are not recorded or sent. The app only generates an anonymous mathematical "fingerprint" of the song's beat to fetch the correct lyrics.
            </p>
            <div class="modal-buttons">
                <button id="lsp-btnAceitarPrivacidade" class="btn-accept">Accept</button>
                <button id="lsp-btnRecusarPrivacidade" class="btn-reject">Cancel</button>
            </div>
        </div>
    </div>
    
    <div id="lsp-overlay" style="display: none;"></div>
    `;

    shadow.innerHTML = panelHTML;

    const painel = shadow.getElementById('lsp-panel-container');
    const elMusica = shadow.getElementById('lsp-musica');
    const elArtista = shadow.getElementById('lsp-artista');
    const elStatus = shadow.getElementById('lsp-status');
    const elStatusIcon = shadow.getElementById('lsp-status-icon');
    const btnReconectar = shadow.getElementById('lsp-btnReconectar');
    const elPainelManual = shadow.getElementById('lsp-painelManual');
    const elListaLetra = shadow.getElementById('lsp-listaLetraCompleta');
    const btnSinc = shadow.getElementById('lsp-btnSelecionarLinha');
    const overlay = shadow.getElementById('lsp-overlay');
    
    // Elementos do Modal
    const privacyModal = shadow.getElementById('lsp-privacy-modal');
    const btnAceitarPrivacidade = shadow.getElementById('lsp-btnAceitarPrivacidade');
    const btnRecusarPrivacidade = shadow.getElementById('lsp-btnRecusarPrivacidade');

    function aplicarArraste(elemento, alça) {
        let pos1 = 0, pos2 = 0, pos3 = 0, pos4 = 0;
        alça.onmousedown = (e) => {
            e.preventDefault();
            pos3 = e.clientX;
            pos4 = e.clientY;
            document.onmouseup = () => { document.onmouseup = null; document.onmousemove = null; };
            document.onmousemove = (e) => {
                e.preventDefault();
                pos1 = pos3 - e.clientX;
                pos2 = pos4 - e.clientY;
                pos3 = e.clientX;
                pos4 = e.clientY;
                elemento.style.top = (elemento.offsetTop - pos2) + "px";
                elemento.style.left = (elemento.offsetLeft - pos1) + "px";
                elemento.style.right = "auto";
            };
        };
    }
    aplicarArraste(painel, shadow.getElementById('lsp-drag-handle'));

    shadow.getElementById('lsp-btnIniciar').onclick = () => {
        chrome.storage.local.get(['privacidadeAceita'], function(result) {
            if (result.privacidadeAceita) {
                apiFetch('/iniciar');
            } else {
                privacyModal.style.display = 'flex';
            }
        });
    };

    btnAceitarPrivacidade.onclick = () => {
        chrome.storage.local.set({privacidadeAceita: true}, function() {
            privacyModal.style.display = 'none';
            apiFetch('/iniciar');
        });
    };

    btnRecusarPrivacidade.onclick = () => {
        privacyModal.style.display = 'none';
    };
    
    shadow.getElementById('lsp-btnParar').onclick = () => {
        apiFetch('/parar');
        elMusica.innerText = "Stopped";
        elArtista.innerText = "---";
        elListaLetra.style.display = 'none';
        overlay.style.display = "none"; 
        btnSinc.style.display = "none";
    };

    shadow.getElementById('lsp-btnManual').onclick = () => {
        elPainelManual.style.display = elPainelManual.style.display === 'none' ? 'flex' : 'none';
    };

    shadow.getElementById('lsp-btnBuscarManual').onclick = async () => {
        const art = shadow.getElementById('lsp-iptArtista').value;
        const mus = shadow.getElementById('lsp-iptMusica').value;
        if(!art || !mus) return;
        
        elStatus.innerText = "Searching...";
        
        try {
            const data = await apiFetch(`/buscar_manual?artista=${encodeURIComponent(art)}&musica=${encodeURIComponent(mus)}`);
            if(data.status === "sucesso") {
                preencherLista(data.letra_completa);
                elListaLetra.style.display = 'block';
                elPainelManual.style.display = 'none'; 
            } else {
                elStatus.innerText = "Lyrics not found!";
                setTimeout(() => { elStatus.innerText = "Alt + M to hide"; }, 3000);
            }
        } catch (e) {
            elStatus.innerText = "Connection error while searching.";
            setTimeout(() => { elStatus.innerText = "Alt + M to hide"; }, 3000);
        }
    };

    btnSinc.onclick = async () => {
        if (elListaLetra.style.display === 'block') { elListaLetra.style.display = 'none'; return; }
        try {
            const data = await apiFetch('/letra_completa');
            if(data.status === "sucesso") {
                preencherLista(data.letra);
                elListaLetra.style.display = 'block';
            }
        } catch (e) {
            console.error(e);
        }
    };

    function preencherLista(letra) {
        elListaLetra.innerHTML = '';
        letra.forEach(item => {
            const d = document.createElement('div');
            d.className = 'lsp-linha-clicavel';
            d.innerText = item.letra;
            d.onclick = () => {
                apiFetch(`/sincronizar_manual?tempo=${item.tempo}`);
                elListaLetra.style.display = 'none';
            };
            elListaLetra.appendChild(d);
        });
    }

    document.addEventListener('keydown', (e) => {
        if (e.altKey && e.key.toLowerCase() === 'm') {
            painel.style.display = painel.style.display === 'none' ? 'block' : 'none';
        }
    });

    let isDragging = false, offsetO = [0,0];
    overlay.ondragstart = () => false;

    overlay.addEventListener('mousedown', (e) => {
        const rect = overlay.getBoundingClientRect();
        const distanceFromRight = rect.right - e.clientX;
        const distanceFromBottom = rect.bottom - e.clientY;
        if (distanceFromRight < 20 && distanceFromBottom < 20) return; 

        isDragging = true;
        offsetO = [overlay.offsetLeft - e.clientX, overlay.offsetTop - e.clientY];
        overlay.style.cursor = "grabbing";
    });

    window.addEventListener('mousemove', (e) => {
        if (!isDragging) return;
        e.preventDefault(); 
        
        overlay.style.left = (e.clientX + offsetO[0]) + "px";
        overlay.style.top = (e.clientY + offsetO[1]) + "px";
        overlay.style.bottom = "auto";
        overlay.style.transform = "none";
    });

    window.addEventListener('mouseup', () => { 
        isDragging = false; 
        overlay.style.cursor = "grab"; 
    });

    function atualizarLetraNoOverlay(data) {
        overlay.innerHTML = '';
        
        const styleSide = "font-size: 16px; color: #888; margin: 5px 0; pointer-events: none; width: 95%; word-wrap: break-word; white-space: normal;";
        const styleMain = "font-size: 24px; font-weight: bold; color: #999b79; margin: 10px 0; pointer-events: none; width: 100%; word-wrap: break-word; white-space: normal; line-height: 1.2;";

        if (data.busca_concluida && !data.letra_encontrada) {
            const p = document.createElement('div'); 
            p.style.cssText = styleMain; 
            p.style.color = "#aaaaaa"; 
            p.innerText = "Sorry, lyrics not found"; 
            overlay.appendChild(p);
            return;
        }

        if(data.linha_anterior) {
            const p = document.createElement('div'); p.style.cssText = styleSide; p.innerText = data.linha_anterior; overlay.appendChild(p);
        }
        
        if(data.linha_atual) {
            const p = document.createElement('div'); p.style.cssText = styleMain; p.innerText = data.linha_atual; overlay.appendChild(p);
        } else if (data.letra_encontrada) {
            const p = document.createElement('div'); p.style.cssText = styleMain; p.innerText = "♫"; overlay.appendChild(p);
        }
        
        if(data.linha_futura) {
            const p = document.createElement('div'); p.style.cssText = styleSide; p.innerText = data.linha_futura; overlay.appendChild(p);
        }
    }

    let loopId;

    async function mainLoop() {
        if (document.hidden) return;

        try {
            const data = await apiFetch('/status');

            elStatusIcon.style.color = "#557a46"; 
            btnReconectar.style.display = "none";

            if(data.escutando) {
                elMusica.innerText = data.musica || "Identifying...";
                elMusica.style.color = "#fff"; 
                elArtista.innerText = data.artista || "---";
                
                if (data.status_msg !== "Alt + M to hide" || elStatus.innerText !== "Lyrics not found!") {
                     elStatus.innerText = data.status_msg;
                }
                
                btnSinc.style.display = data.musica && data.letra_encontrada ? "block" : "none";
                
                overlay.style.display = "flex"; 
                atualizarLetraNoOverlay(data);
            } else {
                elMusica.innerText = "No song...";
                overlay.style.display = "none";
                btnSinc.style.display = "none";
            }
        } catch (e) {
            elStatusIcon.style.color = "#8b4545"; 
            btnReconectar.style.display = "block";
            
            elMusica.innerText = "Server Offline";
            elMusica.style.color = "#8b4545";
            elArtista.innerText = "---";
            elStatus.innerText = "Open FrontLine Lyrics.exe";
            overlay.style.display = "none";
            btnSinc.style.display = "none";
            
            clearInterval(loopId); 
        }
    }

    btnReconectar.onclick = () => {
        elStatusIcon.style.color = "#a08d4c"; 
        btnReconectar.style.display = "none";
        elMusica.innerText = "Connecting...";
        elMusica.style.color = "#888";
        
        mainLoop(); 
        clearInterval(loopId); 
        loopId = setInterval(mainLoop, 500); 
    };

    loopId = setInterval(mainLoop, 500);

    chrome.runtime.onMessage.addListener((request, sender, sendResponse) => {
        if (request.action === "desligar") {
            clearInterval(loopId); 
            host.remove(); 
        }
    });

    shadow.getElementById('lsp-fechar-extensao').onclick = () => {
        clearInterval(loopId); 
        host.remove(); 
    };
}