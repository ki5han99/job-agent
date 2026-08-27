from ollama import chat

response = chat(
    model="qwen3.5:9b",
    messages=[
        {
            "role": "user",
            "content": "Reply with exactly: PYTHON_CAN_TALK_TO_QWEN",
        }
    ],
    think=False,
)

print(response.message.content)