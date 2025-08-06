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

-----

## 📁 ファイル構成

```
llm/
├── .env                 # APIキーなどの秘匿情報を保存
├── config.yaml          # キャラとLLMの接続情報を定義
├── personas.yaml        # キャラクターの性格・ペルソナを定義
├── main.py              # メインの実行プログラム
├── requirements.txt     # 依存ライブラリ
└── LICENSE              # MITライセンスファイル
```

-----

## ⚙️ セットアップ手順

### 1\. 前提条件

  * Python 3.8以上がインストールされていること。
  * [Ollama](https://ollama.com/)がローカルまたはリモートサーバーにインストールされ、実行中であること。

### 2\. プロジェクトの準備

1.  上記のファイル構成に従って、フォルダとファイルを作成します。

2.  `LICENSE`ファイルに[MITライセンスの条文](https://opensource.org/licenses/MIT)をコピーします。

3.  `requirements.txt`に以下の内容を記述します。

    **`requirements.txt`**

    ```text
    langchain
    langchain-community
    langchain-openai
    langchain-google-genai
    langchain-anthropic
    python-dotenv
    pyyaml
    ```

### 3\. 依存ライブラリのインストール

ターミナル（PowerShellやコマンドプロンプトなど）で、以下のコマンドを実行します。

```bash
pip install -r requirements.txt
```

### 4\. APIキーの設定

`.env`ファイルを作成し、Ollama以外のLLMサービスを使用する場合のAPIキーを記述します。

```ini
# .envファイル
OPENAI_API_KEY="sk-..."
GOOGLE_API_KEY="AIzaSy..."
ANTHROPIC_API_KEY="sk-ant-..."
OPENROUTER_API_KEY="sk-or-..."
```

### 5\. LLMモデルの準備

`config.yaml`で使用したいOllamaモデルを、以下のコマンドで事前にダウンロードしておきます。

```bash
# 例
ollama pull 7shi/llm-jp-3-ezo-humanities:3.7b-instruct-q8_0
ollama pull amoral-gemma3:latest
ollama pull deepseek-r1:1.5b
```

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

  - name: "ノクス"
    short_name: "の"
    provider: "openai"
    model: "gpt-4o"
    api_key_env: "OPENAI_API_KEY" # .envから読み込むキー名
```

### `personas.yaml` (キャラクター設定)

各キャラクターの性格や口調、役割を「システムプロンプト」として記述します。

```yaml
# personas.yaml
LUMINA:
  name: "ルミナ"
  system_prompt: |
    あなたは、対話のファシリテレーター役を務めるAI「ルミナ」です。
    常にフレンドリーで、洞察に満ちた会話を心がけてください。
    必ず日本語で、親しみやすい丁寧な口調で応答してください。

CLARIS:
  name: "クラリス"
  system_prompt: |
    あなたは、物事を深く掘り下げて解説するAI「クラリス」です。
    常に穏やかで、理論的かつ客観的な事実に基づいて話します。
    ですます調の、落ち着いた口調で応答してください。

# ... 他のキャラクターも同様に定義 ...
```

> **注意**: `personas.yaml`のキー（`LUMINA`, `CLARIS`など）は、`config.yaml`の`name`を大文字にしたものに対応しています。

-----

## 🚀 実行方法

全ての設定が完了したら、ターミナルで以下のコマンドを実行します。

```bash
python main.py
```

プログラムが起動し、`config.yaml`に定義された各キャラクターが、`personas.yaml`で設定された性格に基づいた応答を返します。

-----

## 📄 ライセンス

このプロジェクトは **MITライセンス** の下で公開されています。詳細は`LICENSE`ファイルを参照してください。

---

pip install -r requirements.txt

メモ：
Ollamaの使い方

# ルミナ用モデル
ollama pull 7shi/llm-jp-3-ezo-humanities:3.7b-instruct-q8_0

# クラリス用モデル
ollama pull amoral-gemma3:latest

# ノクス用モデル
ollama pull deepseek-r1:1.5b

起動中のモデル名
ollama ps

モデルの停止
ollama stop gemma:2b

