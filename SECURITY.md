# Security policy

## Reporting a vulnerability

Please do not open a public issue for security problems. Email **hello@quanticdata.io** with the subject "Security: langchain-quanticdata" and include a description, steps to reproduce and the version you use. We acknowledge reports within 3 business days and keep you informed until a fix is released.

## Supported versions

| Version | Supported |
| --- | --- |
| 0.1.x | yes |

## API keys

Never commit an API key. The package reads `QUANTICDATA_API_KEY` from the environment (or the `api_key` argument, stored as a pydantic `SecretStr` on the tools and the retriever) and sends it only in the `Authorization` header to the API base URL. robots.txt requests go to the sites themselves and carry no key. If a key leaks, rotate it on the API keys page of the QuanticData dashboard.

## Prompt injection

Pages and search results are untrusted text written by third parties. When an agent reads them through these tools, they can contain instructions aimed at the model. Do not give the same agent tools with side effects (payments, email, shell) without a human check.
