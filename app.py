import discord
from openai import OpenAI

import config

aiclient = OpenAI(api_key=config.OPENAI_API_KEY)


class Sphene:
    def __init__(self, system_setting: str) -> None:
        # システムの設定をセットする
        self.system = {"role": "system", "content": system_setting}
        # ユーザーの入力を保持するためのリストを初期化する
        self.input_list = [self.system]
        # ログを保持するためのリストを初期化する
        self.logs: list = []

    # ユーザーからの入力を受け取り、OpenAI APIを使って回答を生成する
    def input_message(self, input_text: str) -> None:
        # ユーザーの入力をリストに追加する
        self.input_list.append({"role": "user", "content": input_text})
        # OpenAI APIを使って回答を生成する
        result = aiclient.chat.completions.create(
            model="gpt-4o-mini", messages=self.input_list
        )
        # 生成した回答をログに追加する
        self.logs.append(result)
        # 生成した回答をリストに追加する
        self.input_list.append(
            {"role": "assistant", "content": result.choices[0].message.content}
        )


# Discord Botを作成するための準備
intents = discord.Intents.all()
client = discord.Client(intents=intents)


# Discord Botが起動したときに呼び出される関数
@client.event
async def on_ready() -> None:
    print("ready to go.")


# Discordでメッセージが送信されたときに呼び出される関数
@client.event
async def on_message(message) -> None:
    # Bot自身が送信したメッセージには反応しない
    if message.author == client.user:
        return
    if message.author.bot:
        return

    # ユーザーからの質問を受け取る
    if client.user in message.mentions:
        question = message.content[4:]

        # ChatGPTクラスを使って回答を生成する
        api = Sphene(system_setting="あなたはアシスタントです。会話を開始します。")
        api.input_message(question)

        # 生成した回答を取得する
        answer = api.input_list[-1]["content"]

        # 回答を送信する
        await message.channel.send(answer)


# Discord Botを起動する
client.run(config.DISCORD_TOKEN)
