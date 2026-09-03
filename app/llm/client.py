from ollama import chat

MODEL_NAME = "qwen3.5:9b"


def ask_llm(
    prompt: str,
    temperature: float = 0.2,
) -> str:
    response = chat(
        model=MODEL_NAME,
        messages=[
            {
                "role": "user",
                "content": prompt,
            }
        ],
        think=False,
        options={
            "temperature": temperature,
        },
    )

    return response.message.content