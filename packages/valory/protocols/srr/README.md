# Simple-Request-Response Protocol

## Description

This is a simple protocol for basic json-based request-response interactions.

## Specification

```yaml
---
name: srr
author: valory
version: 0.1.0
description: A protocol for basic json-based request-response interactions.
license: Apache-2.0
aea_version: '>=1.0.0, <2.0.0'
protocol_specification_id: valory/srr:0.1.0
speech_acts:
  request:
    payload: pt:str
  response:
    payload: pt:str
    error: pt:bool
...
---
initiation: [request]
reply:
  request: [response]
  response: []
termination: [response]
roles: {skill, connection}
end_states: [successful]
keep_terminal_state_dialogues: false
...
```

## Links

