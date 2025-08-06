document.addEventListener('DOMContentLoaded', () => {

    // --- DOM要素の取得 ---
    const chatLog = document.getElementById('chat-log');
    const chatForm = document.getElementById('chat-form');
    const userInput = document.getElementById('user-input');
    const sendButton = document.getElementById('send-button');
    const statusElements = {
        LUMINA: document.getElementById('lumina-state'),
        CLARIS: document.getElementById('claris-state'),
        NOX: document.getElementById('nox-state')
    };
    
    // ★★★ WebSocketのセットアップ ★★★
    const ws = new WebSocket(`ws://${window.location.host}/ws`);

    ws.onopen = (event) => {
        console.log("サーバーに接続しました。");
        addSystemMessage("サーバーに接続しました。");
    };

    ws.onmessage = (event) => {
        const data = JSON.parse(event.data);

        // サーバーから受信したメッセージのタイプに応じて処理を分岐
        if (data.type === 'message') {
            // 新しいメッセージをログに追加
            addMessage(data.speaker, data.text);
        } else if (data.type === 'status') {
            // キャラクターステータスを更新
            updateStatus(data.character, data.status);
        }
    };

    ws.onerror = (error) => {
        console.error("WebSocketエラー:", error);
        addSystemMessage("エラーが発生しました。サーバーとの接続を確認してください。");
    };

    ws.onclose = () => {
        console.log("サーバーから切断されました。");
        addSystemMessage("サーバーから切断されました。ページをリロードしてください。");
        setInteractionState(false);
    };

    // --- イベントハンドラ ---
    const handleFormSubmit = (e) => {
        e.preventDefault();
        const userMessage = userInput.value.trim();
        if (userMessage && ws.readyState === WebSocket.OPEN) {
            // ユーザーのメッセージをログに追加
            addMessage('USER', userMessage);
            // WebSocket経由でサーバーにメッセージを送信
            ws.send(userMessage);
            userInput.value = '';
        }
    };
    
    // --- 初期化処理 ---
    const init = () => {
        chatForm.addEventListener('submit', handleFormSubmit);
    };

    // --- UIヘルパー関数 (一部修正) ---
    const addMessage = (speaker, text) => {
        const messageElement = createMessageElement(speaker, text);
        chatLog.appendChild(messageElement);
        scrollToBottom();
    };
    
    const addSystemMessage = (text) => {
        const msgDiv = document.createElement('div');
        msgDiv.className = 'system-info';
        msgDiv.textContent = text;
        chatLog.appendChild(msgDiv);
        scrollToBottom();
    };

    const updateStatus = (character, status) => {
        // personas.yamlのキーは常に大文字なので、それに合わせる
        const key = character.toUpperCase(); 
        const element = statusElements[key];
        if (!element) return;
        
        element.textContent = `● ${status}`;
        element.className = `char-state ${status.toLowerCase()}`;
    };

    // (createMessageElement, setInteractionState, getSpeakerInfo, scrollToBottomは変更なし)
    const createMessageElement = (speaker, text) => {
        const speakerInfo = getSpeakerInfo(speaker);
        const messageDiv = document.createElement('div');
        messageDiv.className = `chat-message ${speakerInfo.cssClass}`;
        const avatarHTML = `<div class="avatar-container"><div class="avatar ${speakerInfo.avatarClass}">${speakerInfo.avatarInitial}</div></div>`;
        const bodyHTML = `<div class="message-body"><div class="speaker-name">${speaker.toUpperCase()}</div><div class="message-content"><p>${text}</p></div><div class="timestamp">${new Date().toLocaleTimeString('ja-JP')}</div></div>`;
        messageDiv.innerHTML = (speaker === 'USER') ? bodyHTML + avatarHTML : avatarHTML + bodyHTML;
        return messageDiv;
    };
    const setInteractionState = (isEnabled) => { userInput.disabled = !isEnabled; sendButton.disabled = !isEnabled; if (isEnabled) userInput.focus(); };
    const getSpeakerInfo = (speaker) => {
        const key = speaker.toUpperCase();
        const info = { USER: { cssClass: 'user-message', avatarClass: 'user-avatar', avatarInitial: 'U' }, LUMINA: { cssClass: 'lumina-message', avatarClass: 'lumina-avatar', avatarInitial: 'L' }, CLARIS: { cssClass: 'claris-message', avatarClass: 'claris-avatar', avatarInitial: 'C' }, NOX: { cssClass: 'nox-message', avatarClass: 'nox-avatar', avatarInitial: 'N' } };
        return info[key] || { cssClass: 'system-message', avatarClass: 'system-avatar', avatarInitial: 'S' };
    };
    const scrollToBottom = () => chatLog.scrollTop = chatLog.scrollHeight;
    
    init();
});
