from ollama import chat


MODEL_NAME = "qwen3.5:9b"


def ask_llm(prompt: str) -> str:
    response = chat(
        model=MODEL_NAME,
        messages=[
            {
                "role": "user",
                "content": prompt,
            }
        ],
        think=False,
    )

    return response.message.content