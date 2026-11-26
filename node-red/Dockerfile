# Node-RED mit vorinstallierten IT-OT-vPLC-Nodes
FROM node:22-alpine AS pack
WORKDIR /src
COPY package.json README.md ./
COPY nodes ./nodes
COPY examples ./examples
RUN mkdir /out && npm pack --pack-destination /out

FROM nodered/node-red:4.1.18-22
COPY --from=pack /out/ /tmp/vplc-nodes/
RUN npm install --no-audit --no-fund --omit=dev /tmp/vplc-nodes/*.tgz \
 && rm -rf /tmp/vplc-nodes
