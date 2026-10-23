# Short text reservation proof

New explicit profile `lightning-text-64k-2026-10-23` reserves $0.01 per request,
or $0.06 for a six-request native trial. The aggregate cap remains $0.75.
Legacy $0.10 and full-context $0.075 reservations, including every unknown outcome,
are unchanged. This profile does not reprice old claims or release unknown costs.

Before reservation or forwarding, the transport enforces at most 65,536 wire
bytes, 32 messages, plain string content with only role/content keys, and only
system/user/assistant roles. Tools, reasoning fields, multimodal content, multiple
completions and other expanding request options are rejected. Requested output is
2,000 tokens; the mathematical bound conservatively uses 2,048.

NVIDIA's official BF16 Lightning tokenizer has no normalizer, an isolating split
followed by ByteLevel preprocessing without a prefix space, and BPE merges.
It cannot produce more ordinary tokens than input UTF-8 bytes. Its text-only
chat-template path emits each content once, removes or trims historical thinking,
and adds fewer than 128 bytes per message, plus fixed framing. The worst text
bound is therefore below 65,536 + 34*128 = 69,888 tokens. The price reservation uses
the looser **131,072 input tokens** to leave additional template margin.

At the currently published $0.06/$0.24 per million input/output tokens, that costs
at most `(131072*0.06 + 2048*0.24)/1e6 = $0.00835584`, below $0.01. Changed model,
unsupported input shape, excessive bytes/messages, or rates that no longer fit
the reserve fail closed. This is an estimate under the published provider/model
contract, not verification of provider billing or a new security guarantee.

Primary sources checked October 23:

- [Nebius model and BF16 pricing](https://nebius.com/services/token-factory/models/nvidia-nemotron-models-inference)
- [NVIDIA tokenizer](https://huggingface.co/nvidia/NVIDIA-Nemotron-3.5-Lightning-30B-A3B-BF16/blob/a9904d24bcc1d289a1950fa9d2b978c47cf903b9/tokenizer.json), SHA256 `623c34567aebb18582765289fbe23d901c62704d6518d71866e0e58db892b5b7`
- [NVIDIA chat template](https://huggingface.co/nvidia/NVIDIA-Nemotron-3.5-Lightning-30B-A3B-BF16/blob/a9904d24bcc1d289a1950fa9d2b978c47cf903b9/chat_template.jinja), SHA256 `58933db77d3099b4f78c55a38347a72e1ea05b97d6bd8f38775303dc0194e0a9`
- Tokenizer configuration SHA256 `10f93eabcb9b1602fbb991d6308e787ce1df28ee9cd7a1c6d1e8c3f338b957bc`

The exact downloaded data files remain under `results/tokenizer-bound-verification`.
No model weights were downloaded. The runtime adds no tokenizer dependency and
does not alter or truncate the actual prompt.
