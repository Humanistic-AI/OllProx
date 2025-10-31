## OllProx
### Proxy for an Ollama server that provides authentication and caching

Ollama is great, but it doesn't support authentication nor caching.
This small wrapper provides an Api-key based authentication.

### To run:
1. Launch your ollama server on this host. Currently you have to launch this outside of docker, which also alows you to configure your GPU at ease.

2. Create a `.env` file based on the example
  *  If you already have a set of salted keys, add the local path to the file containing the keys, one per line, to the `API_KEY_FILE` variable and add the salt to the `API_KEY_SALT` variable.
  *  If you don't have salted keys already, just plain text ones, keep the `API_KEY_SALT` variable empty, and a salt will be created for you
  *  If you don't have any API keys already, you can either create some random ones and add them to 
  * Make sure the `OLLAMA_HOST` and `OLLAMA_PORT` variables point to your ollama server. The ones included in the example work fine if you launch ollama with default setting on Linux, so far.

3. Launch with `docker compose up`

4. If you didn't provide any keys, check the terminal for a valid API key


### To call:

You can now call your Ollama's `/api/generate` endpoint by POSTing to the `ollprox` container's `call_model` endpoint. By default, this is mapped to `http://localhost:8000/call_model`.  Request's have the same format as [Ollama expects according to the doc](https://docs.ollama.com/api/generate). But now you have to add the api key as a header called `apikey` to the request.

This can be done in CURL with
```
curl -X POST http://localhost:8000/call_model \
  -H "APIKEY: secretgardenkey" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "llama2",
    "prompt": "What is the capital of France?"
  }'

  ```

Or in Python requests with

```

import requests

response = requests.post(
    "http://localhost:8000/call_model",
    headers={"APIKEY": "secretgardenkey"},
    json={"model": "llama2", "prompt": "What is the capital of France?"}
)

print(response.json())

```


### To modify keys
* Just change the key's file
* If you revoke a key, it might take up to $KEY_REFRESH$ seconds for it to be invalidated