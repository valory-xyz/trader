# Genai Connection

The Genai connection provides a wrapper around the Google GenerativeAI library.


### Original Implementation  
[Link](https://github.com/valory-xyz/meme-ooorr-test/blob/20c121a9005bd852fedea37ef2bc6b0c30c86d81/packages/dvilela/connections/genai/connection.py#L46)

### Changed in this implementation
- Removed support for models deprecated by Google
- Removed the artificial delay and left it to the implementors to handle rate limiting