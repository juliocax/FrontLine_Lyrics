const abasAtivas = new Set();

chrome.action.onClicked.addListener(async (tab) => {
    if (tab.url.startsWith("chrome://") || tab.url.startsWith("edge://")) {
        console.warn("O FrontLine Lyrics não pode ser ativado em páginas internas do navegador.");
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
            console.error("Erro ao tentar injetar o script:", erro);
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