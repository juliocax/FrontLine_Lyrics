const abasAtivas = new Set();

const rotasPermitidas = [
    '/status', 
    '/iniciar', 
    '/parar', 
    '/letra_completa', 
    '/sincronizar_manual', 
    '/buscar_manual'
];

chrome.action.onClicked.addListener(async (tab) => {
    if (tab.url.startsWith("chrome://") || tab.url.startsWith("edge://")) {
        console.warn("FrontLine Lyrics cannot be activated on internal browser pages.");
        return; 
    }

    if (abasAtivas.has(tab.id)) {
        chrome.tabs.sendMessage(tab.id, { action: "desligar" });
        abasAtivas.delete(tab.id);
    }
    
    else {
        try {
            await chrome.scripting.executeScript({
                target: { tabId: tab.id },
                files: ["content.js"]
            });
            abasAtivas.add(tab.id);
        } catch (erro) {
            console.error("Error attempting to inject script:", erro);
        }
    }
});

chrome.tabs.onRemoved.addListener((tabId) => {
    abasAtivas.delete(tabId);
});

chrome.tabs.onUpdated.addListener((tabId, changeInfo) => {
    if (changeInfo.status === 'loading') {
        abasAtivas.delete(tabId);
    }
});

chrome.runtime.onMessage.addListener((request, sender, sendResponse) => {
    if (request.action === "api_call") {
        
        const basePath = request.endpoint.split('?')[0];
        
        if (!rotasPermitidas.includes(basePath)) {
            console.warn(`Unauthorized access attempt on route: ${basePath}`);
            sendResponse({ success: false, erro: "Access blocked for security." });
            return true;
        }

        fetch(`http://localhost:5000${request.endpoint}`)
            .then(res => res.json())
            .then(data => sendResponse({ success: true, data }))
            .catch(erro => sendResponse({ success: false, erro: erro.message }));
        
        return true; 
    }
});