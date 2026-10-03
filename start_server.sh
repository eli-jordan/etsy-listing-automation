#!/bin/bash

cd src/ui && npm run build; cd -
uv run etsy-listings ui --port 8000 