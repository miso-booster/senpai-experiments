# Custom Chatbot Connector Examples

## ADA UAM Chatbot Connector Example

```yaml
name: "Ada UAM"
base_url: "https://api.1millionbot.com"
send_message:
  path: "/api/public/messages"
  method: "POST"
  headers:
    Content-Type: "application/json"
    Authorization: "60a3bee2e3987316fed3218f"
  payload_template:
    conversation: "682ce1ce271ce860cffde0fd"
    sender_type: "User"
    sender: "682ce1cefe831160cee700ed"
    bot: "60a3be81f9a6b98f7659a6f9"
    language: "es"
    url: "https://www.uam.es/uam/tecnologias-informacion/servicios-ti/acceso-remoto-red"
    message:
      text: "{user_msg}"
response_path: "response.0.text"
```

## Metro Madrid Chatbot Connector Example

```yaml
name: "Metro Madrid"
base_url: "https://kdcaapi.metromadrid.es"
send_message:
  path: "/api/KDCA/WidgetMessage"
  method: "POST"
  headers:
    Content-Type: "application/json"
    Origin: "https://www.metromadrid.es"
    Referer: "https://www.metromadrid.es/"
    User-Agent: "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:141.0) Gecko/20100101 Firefox/141.0"
  payload_template:
    idProject: "Mzpv0w4t71t"
    idClient: "0"
    data:
      type: "text"
      content: "{user_msg}"
      buttonId: null
      user:
        nickname: "visitor22842"
        session: "abbda0f6-2197-4787-9d7d-c5107491f7a1"
response_path: "messages.0.content"
```
