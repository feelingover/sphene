from collections import defaultdict
from typing import DefaultDict

import discord
from openai import OpenAI

import config

aiclient = OpenAI(api_key=config.OPENAI_API_KEY)

# ユーザーごとの会話インスタンスを保持する辞書
user_conversations: DefaultDict[str, Sphene] = defaultdict(
    lambda: Sphene(system_setting="あなたはアシスタントです。会話を開始します。")
)


class Sphene:
    def __init__(self, system_setting: str) -> None:
        self.system: dict = {"role": "system", "content": system_setting}
        self.input_list: list = [self.system]
        self.logs: list = []
        # 会話の有効期限を設定（30分）
        self.last_interaction = None

    def input_message(self, input_text: str) -> None:
        self.input_list.append({"role": "user", "content": input_text})
        result = aiclient.chat.completions.create(
            model="gpt-3.5-turbo", messages=self.input_list  # モデル名も修正したよ！
        )
        self.logs.append(result)
        self.input_list.append(
            {"role": "assistant", "content": result.choices[0].message.content}
        )


intents = discord.Intents.all()
client = discord.Client(intents=intents)


@client.event
async def on_ready() -> None:
    print("ready to go.")


@client.event
async def on_message(message: discord.Message) -> None:
    try:
        if message.author == client.user or message.author.bot:
            return

        if client.user in message.mentions:
            question = message.content[4:]
            user_id = str(message.author.id)

            # ユーザーの会話インスタンスを取得
            api = user_conversations[user_id]
            api.input_message(question)
            answer = api.input_list[-1]["content"]

            # 長くなりすぎた会話履歴をリセット（10往復を超えたら）
            if len(api.input_list) > 21:  # system(1) + 10往復(20) = 21
                await message.channel.send(
                    "ごめん！会話が長くなってきたからリセットするね！🔄"
                )
                user_conversations[user_id] = Sphene(
                    system_setting="あなたはアシスタントです。会話を開始します。"
                )
                api = user_conversations[user_id]
                api.input_message(question)
                answer = api.input_list[-1]["content"]

            await message.channel.send(answer)

    except Exception as e:
        await message.channel.send(f"ごめん！エラーが発生しちゃった...😢: {str(e)}")


client.run(config.DISCORD_TOKEN)
