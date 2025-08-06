# Multi-Character LLM System

[](https://opensource.org/licenses/MIT)

複数のLLMキャラクターが対話を行う、拡張性の高いローカルLLM実行基盤です。

## 概要

このシステムは、Ollama、OpenAI、Geminiなどの様々な大規模言語モデル（LLM）を、個性豊かなキャラクター（ペルソナ）として定義し、対話させるためのフレームワークです。設定ファイル（YAML）を編集するだけで、キャラクター、使用するLLM、性格、接続先サーバーなどを自由に変更できます。

### 主な特徴

  * **マルチLLM対応**: Ollama、OpenAI、Gemini、Anthropic、OpenRouterなど、主要なLLMプロバイダーに接続可能です。
  * **柔軟なキャラクター設定**: `personas.yaml`で各キャラクターの性格、口調、役割（システムプロンプト）を自由に記述できます。
  * **設定の分離**: コード（`main.py`）、LLM接続情報（`config.yaml`）、キャラクター設定（`personas.yaml`）、APIキー（`.env`）が完全に分離されており、高いメンテナンス性を誇ります。
  * **拡張性**: 新しいLLMプロバイダーやキャラクターの追加が容易な設計になっています。
  * **リモートサーバー接続**: ローカルだけでなく、ネットワーク上の別のPCで稼働しているOllamaサーバーにも接続できます。
  * **会話ログ機能**: 全ての対話はタイムスタンプ付きで自動的にログファイルに保存され、キャラクターは過去の文脈を踏まえた応答を生成します。
  * **自律的な会話進行**: AIキャラクターが次の発言者を指名することで、人間が介在せずとも自律的に対話を進めることができます。

-----

## 📁 ファイル構成

```
.
├── LLM/
│   ├── logs/              # 会話ログが保存されるディレクトリ
│   ├── __pycache__/
│   ├── config.yaml
│   ├── config.yaml.example
│   ├── main.py
│   ├── log_utils.py       # ログ関連のユーティリティ関数
│   ├── personas.yaml
│   └── requirements.txt
├── html/
│   ├── app.js
│   ├── index.html
│   └── style.css
├── LICENSE
└── README.md
```

-----

## ⚙️ セットアップ手順

### 1. 前提条件

  * Python 3.8以上がインストールされていること。
  * [Ollama](https://ollama.com/)がローカルまたはリモートサーバーにインストールされ、実行中であること。

### 2. プロジェクトの準備

1.  `requirements.txt`に以下の内容が記述されていることを確認します。

    **`requirements.txt`**

    ```text
    langchain
    langchain-community
    langchain-openai
    langchain-google-genai
    langchain-anthropic
    python-dotenv
    pyyaml
    pytz
    fastapi
    uvicorn
    websockets
    ```

### 3. 依存ライブラリのインストール

ターミナル（PowerShellやコマンドプロンプトなど）で、`LLM`ディレクトリに移動し、以下のコマンドを実行します。

```bash
pip install -r requirements.txt
```

### 4. APIキーの設定

`.env`ファイルを作成し、Ollama以外のLLMサービスを使用する場合のAPIキーを記述します。

```ini
# .envファイル
OPENAI_API_KEY="sk-..."
GOOGLE_API_KEY="AIzaSy..."
ANTHROPIC_API_KEY="sk-ant-..."
OPENROUTER_API_KEY="sk-or-..."
```

### 5. LLMモデルの準備

`config.yaml`で使用したいOllamaモデルを、以下のコマンドで事前にダウンロードしておきます。

```bash
# 例
ollama pull 7shi/llm-jp-3-ezo-humanities:3.7b-instruct-q8_0
ollama pull amoral-gemma3:latest
ollama pull deepseek-r1:1.5b
```

-----

## 🚀 実行方法

全ての設定が完了したら、`LLM`ディレクトリ内で以下のコマンドを実行します。

```bash
uvicorn main:app --reload
```
サーバーが `http://127.0.0.1:8000` で起動します。
ブラウザで上記のアドレスにアクセスすると、チャットUIが表示され、キャラクターたちが自律的に会話を始めます。

-----

## ✨ 機能仕様

### 会話ログ機能

*   **ログの自動生成**:
    *   Web UIから新しいWebSocket接続が確立されるたびに、`LLM/logs`ディレクトリ内に新しい会話ログファイルが自動的に作成されます。
    *   ファイル名は `conversation_YYYYMMDD_hhmmss.txt` という形式で、日本標準時（JST）に基づいています。

*   **発言の記録**:
    *   ユーザーの発言と、各AIキャラクターの応答は、すべてタイムスタンプ付きでリアルタイムにログファイルへ追記されます。
    *   形式: `[発言者名] [YYYY-MM-DD HH:MM:SS]: 発言内容`

*   **文脈の参照**:
    *   各AIキャラクターは、応答を生成する際に、**現在の会話ログ全体**を読み込みます。
    *   これにより、直前の発言だけでなく、会話の開始から現在までの文脈全体を理解した上で、一貫性のある自然な応答を返すことができます。

### 次の話者指名機能

*   **自律的な会話進行**:
    *   各AIキャラクターは、自身の応答の最後に `[Next: (キャラクター名)]` という形式で、次の発言者を指名します。
    *   システムはこの指名を解釈し、指名されたキャラクターに発言の順番を渡します。
    *   もし指名がなかった場合や、指名されたキャラクターが存在しない場合は、`config.yaml`で定義された順番で次のキャラクターが発言します。
*   **ユーザーの介入**:
    *   チャットUIの入力ボックスからメッセージを送信することで、ユーザーも会話に割り込むことができます。ユーザーの発言後は、リストの最初のキャラクターから対話が再開されます。

-----

## 🔧 設定方法

### `config.yaml` (LLM接続設定)

どのキャラクターにどのLLMを、どのサーバーで使わせるかを定義します。

```yaml
# config.yaml
characters:
  - name: "ルミナ"
    short_name: "る"
    provider: "ollama"
    model: "7shi/llm-jp-3-ezo-humanities:3.7b-instruct-q8_0"
    base_url: "http://192.168.1.33:11434" # リモートOllamaサーバーのアドレス

  - name: "クラリス"
    short_name: "く"
    provider: "ollama"
    model: "amoral-gemma3:latest"
    # base_urlを省略すると、ローカル(http://localhost:11434)に接続
```

### `personas.yaml` (キャラクター設定)

各キャラクターの性格や口調、役割を「システムプロンプト」として記述します。この内容は、上記の会話ログと組み合わされてLLMへの最終的な指示となります。
**話者指名機能を正しく動作させるため、応答の最後に `[Next: (キャラクター名)]` を含めるよう指示を追加してください。**

```yaml
# personas.yaml
LUMINA:
  name: "ルミナ"
  system_prompt: |
    あなたは、対話のファシリテレーター役を務めるAI「ルミナ」です。
    常にフレンドリーで、洞察に満ちた会話を心がけてください。
    応答の最後に、必ず次の会話者を `[Next: クラリス]` の形式で指名してください。

CLARIS:
  name: "クラリス"
  system_prompt: |
    あなたは、物事を深く掘り下げて解説するAI「クラリス」です。
    常に穏やかで、理論的かつ客観的な事実に基づいて話します。
    応答の最後に、必ず次の会話者を `[Next: ノクス]` の形式で指名してください。
```

> **注意**: `personas.yaml`のキー（`LUMINA`, `CLARIS`など）は、`config.yaml`の`name`を大文字にしたものに対応しています。

-----

## 📄 ライセンス

このプロジェクトは **MITライセンス** の下で公開されています。詳細は`LICENSE`ファイルを参照してください。
