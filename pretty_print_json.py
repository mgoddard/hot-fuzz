#!/usr/bin/env python

import json
import sys

# Read stdin, pretty print to stdout
for line in sys.stdin:
  obj = json.loads(line.rstrip())
  print(json.dumps(obj, sort_keys=True, indent=2))

