
if (window.projetoFestivalInjetado) {
    console.log("Projeto Festival já está rodando nesta aba.");
} else {
    window.projetoFestivalInjetado = true;

    const SERVER_URL = "http://localhost:5000";

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
            
            #lsp-btnSelecionarLinha { background: #4a90e2 !important; color: white !important; border-color: #4a90e2 !important; display: none; width: 100%; margin-top: 8px; }
            
            #lsp-painelManual { border-top: 1px solid #444; padding-top: 10px; display: none; flex-direction: column; gap: 8px; margin-top: 10px; }
            #lsp-painelManual input { background: #111; border: 1px solid #444; color: #e0e0e0; padding: 8px; border-radius: 4px; font-size: 13px; outline: none; }
            #lsp-painelManual input:focus { border-color: #4a90e2; }
            
            #lsp-listaLetraCompleta { max-height: 150px; overflow-y: auto; background: #111; border: 1px solid #444; border-radius: 4px; display: none; font-size: 12px; padding: 5px; margin-top: 10px; }
            .lsp-linha-clicavel { padding: 6px; cursor: pointer; color: #888; border-bottom: 1px solid #222; }
            .lsp-linha-clicavel:hover { background: #222; color: #fff; }
            
            #lsp-status { font-size: 10px; color: #666; text-align: center; margin-top: 10px; }
        </style>
        
        <div class="lsp-header" id="lsp-drag-handle">
            <h2>Projeto Festival</h2>
            <div id="lsp-status-icon" style="color: #555;">●</div>
        </div>

        <div class="lsp-music-info">
            <div id="lsp-musica">Aguardando...</div>
            <div id="lsp-artista">---</div>
        </div>

        <div class="lsp-controls-row">
            <button id="lsp-btnIniciar">Ouvir</button>
            <button id="lsp-btnParar">Parar</button>
            <button id="lsp-btnManual">Letra</button>
        </div>

        <button id="lsp-btnSelecionarLinha">Sincronia Manual</button>
        <div id="lsp-listaLetraCompleta"></div>

        <div id="lsp-painelManual">
            <input type="text" id="lsp-iptArtista" placeholder="Artista">
            <input type="text" id="lsp-iptMusica" placeholder="Música">
            <button id="lsp-btnBuscarManual">Buscar</button>
        </div>
        
        <div id="lsp-status">Alt + M para ocultar</div>
    </div>
    `;

    document.body.insertAdjacentHTML('beforeend', panelHTML);

    const painel = document.getElementById('lsp-panel-container');
    const elMusica = document.getElementById('lsp-musica');
    const elArtista = document.getElementById('lsp-artista');
    const elStatus = document.getElementById('lsp-status');
    const elStatusIcon = document.getElementById('lsp-status-icon');
    const elPainelManual = document.getElementById('lsp-painelManual');
    const elListaLetra = document.getElementById('lsp-listaLetraCompleta');
    const btnSinc = document.getElementById('lsp-btnSelecionarLinha');

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
    aplicarArraste(painel, document.getElementById('lsp-drag-handle'));

    document.getElementById('lsp-btnIniciar').onclick = () => fetch(`${SERVER_URL}/iniciar`);
    document.getElementById('lsp-btnParar').onclick = () => {
        fetch(`${SERVER_URL}/parar`);
        elMusica.innerText = "Parado";
        elListaLetra.style.display = 'none';
    };
    document.getElementById('lsp-btnManual').onclick = () => {
        elPainelManual.style.display = elPainelManual.style.display === 'none' ? 'flex' : 'none';
    };

    document.getElementById('lsp-btnBuscarManual').onclick = async () => {
        const art = document.getElementById('lsp-iptArtista').value;
        const mus = document.getElementById('lsp-iptMusica').value;
        if(!art || !mus) return;
        elStatus.innerText = "Buscando...";
        const res = await fetch(`${SERVER_URL}/buscar_manual?artista=${encodeURIComponent(art)}&musica=${encodeURIComponent(mus)}`);
        const data = await res.json();
        if(data.status === "sucesso") {
            preencherLista(data.letra_completa);
            elStatus.innerText = "Letra carregada!";
        }
    };

    btnSinc.onclick = async () => {
        if (elListaLetra.style.display === 'block') { elListaLetra.style.display = 'none'; return; }
        const res = await fetch(`${SERVER_URL}/letra_completa`);
        const data = await res.json();
        if(data.status === "sucesso") {
            preencherLista(data.letra);
            elListaLetra.style.display = 'block';
        }
    };

    function preencherLista(letra) {
        elListaLetra.innerHTML = '';
        letra.forEach(item => {
            const d = document.createElement('div');
            d.className = 'lsp-linha-clicavel';
            d.innerText = item.letra;
            d.onclick = () => {
                fetch(`${SERVER_URL}/sincronizar_manual?tempo=${item.tempo}`);
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

    const overlay = document.createElement('div');
    overlay.id = "lsp-overlay";

    overlay.style.cssText = `
        position: fixed; bottom: 80px; left: 50%; transform: translateX(-50%);
        z-index: 2147483646; background: rgba(0,0,0,0.85); color: white;
        border-radius: 10px; text-align: center;
        cursor: grab; user-select: none;
        
        /* Tamanho Fixo Inicial */
        width: 450px; 
        height: 160px; 
        
        /* Permite Redimensionar */
        resize: both; 
        overflow: hidden; /* Impede que o conteúdo empurre a borda */
        
        /* Garante que o conteúdo interno fique centralizado */
        display: flex; flex-direction: column; justify-content: center; align-items: center;
        padding: 10px;
    `;
    document.body.appendChild(overlay);

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

        if(data.linha_anterior) {
            const p = document.createElement('div'); p.style.cssText = styleSide; p.innerText = data.linha_anterior; overlay.appendChild(p);
        }
        if(data.linha_atual) {
            const p = document.createElement('div'); p.style.cssText = styleMain; p.innerText = data.linha_atual; overlay.appendChild(p);
        }
        if(data.linha_futura) {
            const p = document.createElement('div'); p.style.cssText = styleSide; p.innerText = data.linha_futura; overlay.appendChild(p);
        }
    }

    async function mainLoop() {
        try {
            const res = await fetch(`${SERVER_URL}/status`);
            const data = await res.json();

            if(data.escutando) {
                elMusica.innerText = data.musica || "Identificando...";
                elArtista.innerText = data.artista || "---";
                elStatusIcon.style.color = data.musica ? "#4a90e2" : "#f1c40f";
                elStatus.innerText = data.status_msg;
                btnSinc.style.display = data.linha_atual ? "block" : "none";
                
                overlay.style.display = "flex"; 
                atualizarLetraNoOverlay(data);
            } else {
                overlay.style.display = "none";
                elStatusIcon.style.color = "#555";
            }
        } catch (e) {
            elStatusIcon.style.color = "red";
            elStatus.innerText = "Python Offline";
        }
    }

    setInterval(mainLoop, 500);

    let loopId = setInterval(mainLoop, 500);

    chrome.runtime.onMessage.addListener((request, sender, sendResponse) => {
        if (request.action === "desligar") {
            clearInterval(loopId); 
            
            document.getElementById('lsp-panel-container')?.remove(); 
            document.getElementById('lsp-overlay')?.remove(); 
            
            window.projetoFestivalInjetado = false; 
        }
    });
}