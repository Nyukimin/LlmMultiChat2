document.addEventListener('DOMContentLoaded', () => {

    // --- カスタムログ関数 ---
    const appLog = (level, message, ...args) => {
        const timestamp = new Date().toLocaleTimeString('ja-JP');
        console[level](`[${timestamp}] [APP] ${message}`, ...args);
    };

    appLog('info', 'DOMContentLoaded event fired.');

    // --- DOM要素の取得 ---
    const chatLog = document.getElementById('chat-log');
    const chatForm = document.getElementById('chat-form');
    const userInput = document.getElementById('user-input');
    const sendButton = document.getElementById('send-button');
    // Ingest UIは独立サブセットへ切り出し。メインUIでは扱わない
    // statusElementsは初期化時に動的に構築する
    let statusElements = {};
    let nameMapping = {};
    
    // ★★★ WebSocketのセットアップ ★★★
    const ws = new WebSocket(`ws://${window.location.host}/ws`);
    appLog('info', 'WebSocket initialization attempted with URL:', `ws://${window.location.host}/ws`);

    ws.onopen = (event) => {
        appLog('info', "サーバーに接続しました。", "WebSocket connection opened.");
        addSystemMessage("サーバーに接続しました。");
    };

    ws.onmessage = (event) => {
        appLog('info', 'WebSocket message received:', event.data);
        const data = JSON.parse(event.data);
        console.log('WebSocket message received:', event.data);

        // サーバーから受信したメッセージのタイプに応じて処理を分岐
        if (data.type === 'message') {
            appLog('info', 'Processing message type:', data);
            // 新しいメッセージをログに追加
            addMessage(data.speaker, data.text);
        } else if (data.type === 'status') {
            appLog('info', 'Processing status type:', data);
            // キャラクターステータスを更新
            updateStatus(data.character, data.status);
        } else if (data.type === 'config') {
            appLog('info', 'Processing config type:', data);
            // キャラクター設定情報を受信
            updateCharacterConfig(data.characters);
        } else {
            appLog('warn', 'Unknown message type received:', data);
        }
    };

    ws.onerror = (error) => {
        appLog('error', "WebSocketエラー:", error, "Error details:", error.message || error);
        console.error("WebSocketエラー:", error);
        addSystemMessage("エラーが発生しました。サーバーとの接続を確認してください。");
    };

    ws.onclose = (event) => {
        appLog('info', "サーバーから切断されました。", "Close code:", event.code, "Reason:", event.reason);
        console.log("サーバーから切断されました。");
        addSystemMessage("サーバーから切断されました。ページをリロードしてください。");
        setInteractionState(false);
    };

    // --- イベントハンドラ ---
    const handleFormSubmit = (e) => {
        appLog('info', 'handleFormSubmit called via form submit event.');
        e.preventDefault();
        const userMessage = userInput.value.trim();
        if (userMessage && ws.readyState === WebSocket.OPEN) {
            appLog('info', 'Sending message to server:', userMessage, 'WebSocket state:', ws.readyState);
            // ユーザーのメッセージをログに追加
            addMessage('USER', userMessage);
            // WebSocket経由でサーバーにメッセージを送信
            try {
                ws.send(userMessage);
                appLog('info', 'Message sent successfully:', userMessage);
            } catch (error) {
                appLog('error', 'Failed to send message:', error);
                addSystemMessage("メッセージの送信に失敗しました。接続を確認してください。");
            }
            userInput.value = '';
        } else {
            appLog('warn', 'Message not sent. Either empty message or WebSocket not open.', 'Message:', userMessage, 'WebSocket state:', ws.readyState);
            if (!userMessage) {
                addSystemMessage("メッセージが空です。入力してください。");
            } else {
                addSystemMessage("サーバーに接続されていません。ページをリロードしてください。");
            }
        }
        appLog('info', 'handleFormSubmit finished.');
    };
    
    // --- 追加のイベントリスナー（デバッグ用） ---
    userInput.addEventListener('keypress', (e) => {
        appLog('info', 'Keypress event on userInput detected. Key:', e.key);
        if (e.key === 'Enter') {
            appLog('info', 'Enter key pressed, triggering form submit.');
            handleFormSubmit(e);
        }
    });
    
    sendButton.addEventListener('click', (e) => {
        appLog('info', 'Send button clicked, triggering form submit.');
        handleFormSubmit(e);
    });

    // Ingest機能は別UIへ移譲
    
    // --- 初期化処理 ---
    const init = () => {
        appLog('info', 'Function init called');
        chatForm.addEventListener('submit', handleFormSubmit);
        appLog('info', 'Submit event listener added to chatForm.');
        appLog('info', 'Function init finished.');
    };

    // --- UIヘルパー関数 (一部修正) ---
    const addMessage = (speaker, text) => {
        appLog('info', `Adding message: ${speaker}: ${text}`);
        const messageElement = createMessageElement(speaker, text);
        chatLog.appendChild(messageElement);
        scrollToBottom();
        appLog('info', `Message added: ${speaker}: ${text}`);
    };
    
    const addSystemMessage = (text) => {
        appLog('info', `Adding system message: ${text}`);
        const msgDiv = document.createElement('div');
        msgDiv.className = 'system-info';
        msgDiv.textContent = text;
        chatLog.appendChild(msgDiv);
        scrollToBottom();
        appLog('info', `System message added: ${text}`);
    };

    const updateStatus = (character, status) => {
        appLog('info', `Attempting to update status for ${character} to ${status}`);
        // サーバーから送られてくる名前を英語名にマッピング
        const key = nameMapping[character] || character.toUpperCase();
        const element = statusElements[key];
        if (!element) {
            appLog('warn', `Status element not found for character: ${character}`);
            return;
        }
        
        console.log('Attempting to update status for', character, 'to', status);
        element.textContent = `● ${status}`;
        element.className = `char-state ${status.toLowerCase()}`;
        console.log(`Updating status for ${character} to ${status}`);
        appLog('info', `Status updated for ${character} to ${status}`);
    };

    const updateCharacterConfig = (characters) => {
        appLog('info', 'Updating character configuration.');
        nameMapping = {};
        statusElements = {};
        characters.forEach(char => {
            nameMapping[char.display_name] = char.name;
            // 英語名に基づいてDOM要素を取得
            const elementId = `${char.name.toLowerCase()}-state`;
            statusElements[char.name] = document.getElementById(elementId);
            if (!statusElements[char.name]) {
                appLog('warn', `Status element not found for ID: ${elementId}`);
            }
        });
        appLog('info', 'Character configuration updated.', nameMapping);
    };

    const createMessageElement = (speaker, text) => {
        appLog('info', `Creating message element for speaker: ${speaker}`);
        const speakerInfo = getSpeakerInfo(speaker);

        const messageDiv = document.createElement('div');
        messageDiv.className = `chat-message ${speakerInfo.cssClass}`;

        const avatarContainer = document.createElement('div');
        avatarContainer.className = 'avatar-container';

        const avatarDiv = document.createElement('div');
        avatarDiv.className = 'avatar';
        avatarDiv.textContent = speakerInfo.avatarInitial;
        avatarContainer.appendChild(avatarDiv);

        const messageBody = document.createElement('div');
        messageBody.className = 'message-body';

        const speakerName = document.createElement('div');
        speakerName.className = 'speaker-name';
        speakerName.textContent = speaker;

        const messageContent = document.createElement('div');
        messageContent.className = 'message-content';
        const p = document.createElement('p');
        p.textContent = text;
        messageContent.appendChild(p);
        
        const timestamp = document.createElement('div');
        timestamp.className = 'timestamp';
        timestamp.textContent = new Date().toLocaleTimeString('ja-JP');

        messageBody.appendChild(speakerName);
        messageBody.appendChild(messageContent);
        messageBody.appendChild(timestamp);

        if (speaker === 'USER') {
            messageDiv.appendChild(messageBody);
            messageDiv.appendChild(avatarContainer);
        } else {
            messageDiv.appendChild(avatarContainer);
            messageDiv.appendChild(messageBody);
        }
        
        appLog('info', `Message element created for speaker: ${speaker}`);
        return messageDiv;
    };
    const setInteractionState = (isEnabled) => {
        appLog('info', `Setting interaction state to: ${isEnabled}`);
        userInput.disabled = !isEnabled; 
        sendButton.disabled = !isEnabled; 
        if (isEnabled) userInput.focus(); 
        appLog('info', `Interaction state set to: ${isEnabled}`);
    };
    const getSpeakerInfo = (speaker) => {
        appLog('info', `Getting speaker info for: ${speaker}`);
        const key = nameMapping[speaker] || speaker.toUpperCase();
        // New speaker info mapping based on the new style.css
        const info = {
            USER: { cssClass: 'user-message', avatarInitial: 'U' },
            LUMINA: { cssClass: 'lumina-message', avatarInitial: 'L' },
            CLARIS: { cssClass: 'claris-message', avatarInitial: 'C' },
            NOX: { cssClass: 'nox-message', avatarInitial: 'N' }
        };
        const result = info[key] || { cssClass: 'system-message', avatarInitial: 'S' };
        appLog('info', `Speaker info retrieved for: ${speaker}`);
        return result;
    };
    const scrollToBottom = () => {
        appLog('info', 'Scrolling to bottom.');
        chatLog.scrollTop = chatLog.scrollHeight;
        appLog('info', 'Scrolled to bottom.');
    };
    
    init();
    appLog('info', 'DOMContentLoaded event finished.');
});
