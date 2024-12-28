import discord
from openai import OpenAI

import config

aiclient = OpenAI(api_key=config.OPENAI_API_KEY)


class Sphene:
    def __init__(self, system_setting: str) -> None:
        self.system: dict = {"role": "system", "content": system_setting}
        self.input_list: list = [self.system]
        self.logs: list = []

    def input_message(self, input_text: str) -> None:
        self.input_list.append({"role": "user", "content": input_text})
        result = aiclient.chat.completions.create(
            model="gpt-4o-mini", messages=self.input_list
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
    # Bot自身が送信したメッセージには反応しない
    if message.author == client.user:
        return
    if message.author.bot:
        return

    # ユーザーからの質問を受け取る
    if client.user in message.mentions:
        question = message.content[4:]

        api = Sphene(system_setting="あなたはアシスタントです。会話を開始します。")
        api.input_message(question)
        answer = api.input_list[-1]["content"]
        await message.channel.send(answer)


client.run(config.DISCORD_TOKEN)
