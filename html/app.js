// DOMが読み込まれたら、アプリケーションのロジックを開始する
document.addEventListener('DOMContentLoaded', () => {

    // --- 設定値 ---
    const MOCK_SCENARIO = [
        { speaker: 'NOX', text: '検索...完了。指定のキーワードに合致する映画は3件。クリストファー・ノーラン監督作品を推奨。', delay: 2000 },
        { speaker: 'CLARIS', text: 'ノーラン監督の『メメント』は、記憶と時間軸を巧みに操る構成が見事です。ユーザーの嗜好と高い親和性を持つと考えられます。', delay: 3500 },
        { speaker: 'LUMINA', text: 'だよね！じゃあ次は『メメント』のどんなところが好きか、もっと深掘りして話してみようか！', delay: 2500 }
    ];

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
    
    // --- 初期化処理 ---
    const init = () => {
        addMessage('LUMINA', 'ようこそ！3キャラ会話システムへ。何か知りたいことや、話したいテーマはありますか？');
        chatForm.addEventListener('submit', handleFormSubmit);
    };

    // --- イベントハンドラ ---
    const handleFormSubmit = (e) => {
        e.preventDefault();
        const userMessage = userInput.value.trim();
        if (userMessage) {
            addMessage('USER', userMessage);
            userInput.value = '';
            simulateResponse();
        }
    };

    // --- コア機能 ---
    /**
     * AIの応答をシミュレーションする
     */
    const simulateResponse = async () => {
        setInteractionState(false); // UIを無効化

        for (const turn of MOCK_SCENARIO) {
            await sleep(500);
            const typingMessage = addTypingIndicator(turn.speaker);
            updateStatus(turn.speaker, 'THINKING');
            
            await sleep(turn.delay);
            
            chatLog.removeChild(typingMessage);
            addMessage(turn.speaker, turn.text);
            updateStatus(turn.speaker, 'ACTIVE');

            // 1つ前の発言者をIDLEにする
            const prevIndex = MOCK_SCENARIO.indexOf(turn) - 1;
            if (prevIndex >= 0) {
                updateStatus(MOCK_SCENARIO[prevIndex].speaker, 'IDLE');
            }
        }
        
        await sleep(2000);
        updateStatus(MOCK_SCENARIO[MOCK_SCENARIO.length - 1].speaker, 'IDLE'); // 最後の発言者をIDLEに

        setInteractionState(true); // UIを有効化
    };

    /**
     * メッセージをチャットログに追加する
     * @param {string} speaker - 発言者 (USER, LUMINA, CLARIS, NOX)
     * @param {string} text - メッセージ本文
     */
    const addMessage = (speaker, text) => {
        const messageElement = createMessageElement(speaker, text);
        chatLog.appendChild(messageElement);
        scrollToBottom();
    };

    /**
     * タイピング中のインジケーターを表示する
     * @param {string} speaker - 発言者
     * @returns {HTMLElement} - 生成されたタイピングインジケーター要素
     */
    const addTypingIndicator = (speaker) => {
        const speakerInfo = getSpeakerInfo(speaker);
        const messageDiv = document.createElement('div');
        messageDiv.className = `chat-message ${speakerInfo.cssClass}`;
        messageDiv.innerHTML = `
            <div class="avatar-container">
                <div class="avatar ${speakerInfo.avatarClass}">${speakerInfo.avatarInitial}</div>
            </div>
            <div class="message-body">
                <div class="message-content typing-indicator">
                    <span></span><span></span><span></span>
                </div>
            </div>
        `;
        chatLog.appendChild(messageDiv);
        scrollToBottom();
        return messageDiv;
    };

    // --- UIヘルパー ---
    /**
     * メッセージ要素を生成する
     * @param {string} speaker - 発言者
     * @param {string} text - メッセージ本文
     * @returns {HTMLElement} - 生成されたメッセージ要素
     */
    const createMessageElement = (speaker, text) => {
        const speakerInfo = getSpeakerInfo(speaker);
        const messageDiv = document.createElement('div');
        messageDiv.className = `chat-message ${speakerInfo.cssClass}`;

        const avatarHTML = `
            <div class="avatar-container">
                <div class="avatar ${speakerInfo.avatarClass}">${speakerInfo.avatarInitial}</div>
            </div>`;
        
        const bodyHTML = `
            <div class="message-body">
                <div class="speaker-name">${speaker}</div>
                <div class="message-content"><p>${text}</p></div>
                <div class="timestamp">${new Date().toLocaleTimeString('ja-JP')}</div>
            </div>`;
        
        messageDiv.innerHTML = (speaker === 'USER') ? bodyHTML + avatarHTML : avatarHTML + bodyHTML;
        return messageDiv;
    };

    /**
     * ヘッダーのキャラクターステータスを更新する
     * @param {string} speaker - キャラクター名
     * @param {'ACTIVE'|'IDLE'|'THINKING'} status - 状態
     */
    const updateStatus = (speaker, status) => {
        const element = statusElements[speaker];
        if (!element) return;
        
        element.textContent = `● ${status}`;
        element.className = `char-state ${status.toLowerCase()}`;
    };

    /**
     * ユーザーの入力可否状態を設定する
     * @param {boolean} isEnabled - 有効にするか
     */
    const setInteractionState = (isEnabled) => {
        userInput.disabled = !isEnabled;
        sendButton.disabled = !isEnabled;
        if (isEnabled) userInput.focus();
    };

    /**
     * 発言者の情報（CSSクラスなど）を取得する
     * @param {string} speaker - 発言者
     * @returns {object} - 発言者情報
     */
    const getSpeakerInfo = (speaker) => {
        const info = {
            USER:   { cssClass: 'user-message',   avatarClass: 'user-avatar',   avatarInitial: 'U' },
            LUMINA: { cssClass: 'lumina-message', avatarClass: 'lumina-avatar', avatarInitial: 'L' },
            CLARIS: { cssClass: 'claris-message', avatarClass: 'claris-avatar', avatarInitial: 'C' },
            NOX:    { cssClass: 'nox-message',    avatarClass: 'nox-avatar',    avatarInitial: 'N' }
        };
        return info[speaker] || info.USER;
    };
    
    const scrollToBottom = () => chatLog.scrollTop = chatLog.scrollHeight;
    const sleep = (ms) => new Promise(resolve => setTimeout(resolve, ms));

    // --- アプリケーション実行 ---
    init();
});

