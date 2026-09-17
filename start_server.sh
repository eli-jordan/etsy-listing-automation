#!/bin/bash

cd src/etsy_listings/ui/frontend && npm run build; cd -
uv run etsy-listings ui --browser --port 8000 