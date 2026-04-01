# -*- coding: utf-8 -*-
import json
import os
import sys
import time
from typing import Tuple

from langchain_core.messages import HumanMessage
from langchain_openai import ChatOpenAI

MAX_TRY = 5

log_path = None
api_trace_json_path = None
total_prompt_tokens = 0
total_response_tokens = 0
world_dict = {}


def _get_llm() -> ChatOpenAI:
    model = os.getenv("MODEL_NAME", "deepseek-chat")
    base_url = os.getenv("OPENAI_API_BASE", "https://api.deepseek.com/v1")
    api_key = os.getenv("OPENAI_API_KEY")
    return ChatOpenAI(
        model=model,
        base_url=base_url,
        api_key=api_key,
        temperature=0.1,
    )


def init_log_path(my_log_path):
    global total_prompt_tokens, total_response_tokens, log_path, api_trace_json_path
    log_path = my_log_path if my_log_path else None
    total_prompt_tokens = 0
    total_response_tokens = 0
    if log_path:
        dir_name = os.path.dirname(log_path)
        os.makedirs(dir_name, exist_ok=True)
        api_trace_json_path = os.path.join(dir_name, "api_trace.json")
    else:
        api_trace_json_path = None


def _extract_token_usage(response) -> Tuple[int, int]:
    usage = getattr(response, "usage_metadata", None) or {}
    if usage:
        pt = usage.get("input_tokens") or usage.get("prompt_tokens") or 0
        rt = usage.get("output_tokens") or usage.get("completion_tokens") or 0
        return int(pt), int(rt)
    meta = getattr(response, "response_metadata", None) or {}
    tu = meta.get("token_usage") or {}
    return int(tu.get("prompt_tokens") or 0), int(tu.get("completion_tokens") or 0)


def _api_call(prompt: str) -> tuple:
    llm = _get_llm()
    model = os.getenv("MODEL_NAME", "deepseek-chat")
    print(f"\nUse OpenAI-compatible model: {model}\n")
    response = llm.invoke([HumanMessage(content=prompt)])
    text = (response.content or "").strip()
    prompt_token, response_token = _extract_token_usage(response)
    return text, prompt_token, response_token


def safe_call_llm(input_prompt: str, **kwargs) -> str:
    """
    Call LLM with retries; optional logging to log_path and api_trace.json when init_log_path was set.
    """
    global total_prompt_tokens, total_response_tokens, world_dict

    for i in range(MAX_TRY):
        try:
            if not log_path:
                sys_response, prompt_token, response_token = _api_call(input_prompt)
                print(f"\nsys_response: \n{sys_response}")
                print(f"\n prompt_token,response_token: {prompt_token} {response_token}\n")
            else:
                if api_trace_json_path is None:
                    raise FileExistsError(
                        "log_path or api_trace_json_path is None, init_log_path first!"
                    )
                with open(log_path, "a+", encoding="utf8") as log_fp, open(
                    api_trace_json_path, "a+", encoding="utf8"
                ) as trace_json_fp:
                    print("\n" + "*" * 20 + "\n", file=log_fp)
                    print(input_prompt, file=log_fp)
                    print("\n" + "=" * 20 + "\n", file=log_fp)
                    sys_response, prompt_token, response_token = _api_call(input_prompt)
                    print(sys_response, file=log_fp)
                    print(
                        f"\n prompt_token,response_token: {prompt_token} {response_token}\n",
                        file=log_fp,
                    )
                    print(
                        f"\n prompt_token,response_token: {prompt_token} {response_token}\n"
                    )

                    if len(world_dict) > 0:
                        world_dict = {}

                    if len(kwargs) > 0:
                        world_dict = {}
                        for k, v in kwargs.items():
                            world_dict[k] = v
                    world_dict["response"] = "\n" + sys_response.strip() + "\n"
                    world_dict["input_prompt"] = input_prompt.strip() + "\n"

                    world_dict["prompt_token"] = prompt_token
                    world_dict["response_token"] = response_token

                    total_prompt_tokens += prompt_token
                    total_response_tokens += response_token

                    world_dict["cur_total_prompt_tokens"] = total_prompt_tokens
                    world_dict["cur_total_response_tokens"] = total_response_tokens

                    world_json_str = json.dumps(world_dict, ensure_ascii=False)
                    print(world_json_str, file=trace_json_fp)

                    world_dict = {}
                    world_json_str = ""

                    print(
                        f"\n total_prompt_tokens,total_response_tokens: {total_prompt_tokens} {total_response_tokens}\n",
                        file=log_fp,
                    )
                    print(
                        f"\n total_prompt_tokens,total_response_tokens: {total_prompt_tokens} {total_response_tokens}\n"
                    )
            return sys_response
        except Exception as ex:
            print(ex)
            model = os.getenv("MODEL_NAME", "deepseek-chat")
            print(f"Request {model} failed. try {i} times. Sleep 20 secs.")
            time.sleep(20)

    raise ValueError("safe_call_llm error!")


if __name__ == "__main__":
    res = safe_call_llm("Hello")
    print(res)
