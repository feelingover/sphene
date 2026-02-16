import asyncio
import os
import sys
from pathlib import Path

# プロジェクトルートをパスに追加
sys.path.append(str(Path(__file__).parent.parent))

import config
from ai.conversation import Sphene, generate_contextual_response, load_system_prompt
from log_utils.logger import logger

async def verify():
    print("=== Vertex AI Grounding & Tools Verification ===")
    
    # Grounding設定の確認
    grounding_enabled = os.getenv("ENABLE_GOOGLE_SEARCH_GROUNDING", "false").lower() == "true"
    print(f"ENABLE_GOOGLE_SEARCH_GROUNDING: {grounding_enabled}")
    if not grounding_enabled:
        print("WARNING: Grounding is DISABLED in your environment.")
        print("To test grounding, run with: ENABLE_GOOGLE_SEARCH_GROUNDING=true python scripts/verify_grounding.py")
    
    system_prompt = load_system_prompt()
    sphene = Sphene(system_setting=system_prompt)
    
    test_cases = [
        {
            "name": "XIVAPI Tool Test",
            "prompt": "FF14のアイテム『エクスカリバー』の情報を教えて",
            "type": "conversation"
        },
        {
            "name": "Google Search Grounding Test",
            "prompt": "2026年のFF14ファンフェスの最新情報は何かある？",
            "type": "conversation"
        },
        {
            "name": "Combination Test",
            "prompt": "最新パッチで追加された新アイテムを調べて、その詳細を教えて",
            "type": "conversation"
        },
        {
            "name": "Autonomous Response Simulation",
            "prompt": "最近のFF14のパッチで一番の注目ポイントって何かな？",
            "type": "contextual",
            "context": "User A: FF14のパッチ7.1が公開されたね。\nUser B: 新しいレイドが楽しみ！"
        }
    ]
    
    for case in test_cases:
        print(f"\n--- Testing: {case['name']} ---")
        print(f"Input: {case['prompt']}")
        
        try:
            if case["type"] == "conversation":
                # Sphene.input_message は同期メソッドなので asyncio.to_thread を使用
                response = await asyncio.to_thread(sphene.input_message, case["prompt"])
            else:
                response = await asyncio.to_thread(
                    generate_contextual_response, 
                    channel_context=case["context"], 
                    trigger_message=case["prompt"]
                )
            print(f"Response: {response}")
        except Exception as e:
            print(f"Error during test '{case['name']}': {e}")
            
        print("-" * 40)

if __name__ == "__main__":
    asyncio.run(verify())
