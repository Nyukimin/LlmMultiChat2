document.addEventListener('DOMContentLoaded', () => {

    // --- カスタムログ関数 ---
    const appLog = (level, message, ...args) => {
        const timestamp = new Date().toLocaleTimeString('ja-JP');
        console[level](`[${timestamp}] [APP] ${message}`, ...args);
    };

    appLog('info', 'DOMContentLoaded event fired.');

    // --- DOM要素の取得 ---
    const chatLog = document.getElementById('chat-log');
    const sysLogsEl = document.getElementById('system-logs');
    const chatForm = document.getElementById('chat-form');
    const userInput = document.getElementById('user-input');
    const sendButton = document.getElementById('send-button');
    const infoSearchToggle = document.getElementById('info-search-toggle');
    // Ingest UIは独立サブセットへ切り出し。メインUIでは扱わない
    // statusElementsは初期化時に動的に構築する
    let statusElements = {};
    let nameMapping = {};
    let shortNameMapping = {};
    
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
                // 先に現在の検索モード状態を送信してサーバ側フラグを更新
                try {
                    const on = !!infoSearchToggle?.checked;
                    ws.send(`/kbauto ${on ? 'on' : 'off'}`);
                } catch (e) {}
                ws.send(userMessage);
                appLog('info', 'Message sent successfully:', userMessage);
            } catch (error) {
                appLog('error', 'Failed to send message:', error);
                addSystemMessage("メッセージの送信に失敗しました。接続を確認してください。");
            }
            userInput.value = '';
            // 送信後は不要
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
        // タブ切替
        const tabChat = document.getElementById('tab-chat');
        const tabLogs = document.getElementById('tab-logs');
        const panelChat = document.getElementById('panel-chat');
        const panelLogs = document.getElementById('panel-logs');
        const activateTab = (tab) => {
            if (tab === 'chat') {
                tabChat.classList.add('active');
                tabLogs.classList.remove('active');
                panelChat.style.display = '';
                panelLogs.style.display = 'none';
            } else {
                tabChat.classList.remove('active');
                tabLogs.classList.add('active');
                panelChat.style.display = 'none';
                panelLogs.style.display = '';
                // 自動スクロール
                sysLogsEl.scrollTop = sysLogsEl.scrollHeight;
            }
        };
        tabChat.addEventListener('click', () => activateTab('chat'));
        tabLogs.addEventListener('click', () => activateTab('logs'));
        // 情報検索モードの保存/復元
        try {
            const saved = localStorage.getItem('infoSearchMode');
            if (saved !== null && infoSearchToggle) {
                infoSearchToggle.checked = saved === '1';
            }
            infoSearchToggle?.addEventListener('change', () => {
                localStorage.setItem('infoSearchMode', infoSearchToggle.checked ? '1' : '0');
            });
        } catch (e) {}
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
        // 画面ログにも出力
        if (sysLogsEl) {
            const ts = new Date().toLocaleTimeString('ja-JP');
            sysLogsEl.textContent += `[${ts}] ${text}\n`;
            sysLogsEl.scrollTop = sysLogsEl.scrollHeight;
        }
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
        // 動的にステータス行を再構築（最大5名）
        const panel = document.querySelector('.status-panel');
        if (panel) {
            while (panel.firstChild) panel.removeChild(panel.firstChild);
            const max = Math.min(5, (characters || []).length);
            for (let i = 0; i < max; i++) {
                const char = characters[i];
                const row = document.createElement('div');
                row.className = 'char-status';
                // アイコン
                const icon = document.createElement('span');
                icon.className = 'char-icon';
                const dn = (char.display_name || char.name || '?');
                const short = (char.short_name || '').trim();
                icon.textContent = short ? short : (dn[0] || '?');
                // 名前
                const nameText = document.createTextNode(' ' + (char.name || 'UNKNOWN')); // 内部名を表示
                // 状態
                const state = document.createElement('span');
                state.className = 'char-state idle';
                state.textContent = '● IDLE';
                row.appendChild(icon);
                row.appendChild(document.createTextNode((char.display_name || char.name || '')));
                row.appendChild(document.createTextNode(' '));
                row.appendChild(state);
                panel.appendChild(row);
                nameMapping[char.display_name] = char.name;
                shortNameMapping[char.display_name] = short || (dn[0] || '?');
                statusElements[char.name] = state;
                // 文字色テーマ（上部バーと整合）
                try {
                    const themeClass = `${char.name.toLowerCase()}-status`;
                    row.classList.add(themeClass);
                } catch (e) {}
            }
            if ((characters || []).length > 5) {
                appLog('warn', 'More than 5 characters provided; showing first 5.');
                // 画面ログにも警告
                addSystemMessage('参加キャラクターが多いため、先頭5名のみ表示しています。');
            }
        }
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
        // キャラごとの色クラスをアバターへ付与
        switch (speakerInfo.cssClass) {
            case 'lumina-message':
                avatarDiv.classList.add('lumina-avatar');
                break;
            case 'claris-message':
                avatarDiv.classList.add('claris-avatar');
                break;
            case 'nox-message':
                avatarDiv.classList.add('nox-avatar');
                break;
            case 'user-message':
            default:
                // ユーザーは CSS 側で .user-message .avatar にて色付け
                break;
        }
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
        // avatar は display_name → short_name を優先
        if (speaker === 'USER') {
            result.avatarInitial = 'U';
        } else {
            const sn = shortNameMapping[speaker];
            result.avatarInitial = (sn && sn.length) ? sn : ((speaker || 'S').charAt(0));
        }
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
