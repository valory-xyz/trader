import json
from copy import deepcopy

import requests

version = "v0.10.8"
remote_url = f"https://raw.githubusercontent.com/valory-xyz/open-autonomy/{version}/packages/packages.json"

with open("packages/packages.json") as f:
    old = json.load(f)

remote_dev, remote_third_party = requests.get(remote_url).json().values()
remote = {**remote_dev, **remote_third_party}

new = deepcopy(old)
for key, value in old["third_party"].items():
    if key in remote:
        new["third_party"][key] = remote[key]

print(json.dumps(new, indent=4))
