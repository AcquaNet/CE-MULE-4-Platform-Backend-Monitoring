ELK Stack + APISIX Gateway - Single Archive Export
==================================================

Export Date: 2026-01-05
File: elk-stack-all-images.tar
Size: 1.9 GB

IMAGES INCLUDED (10 images)
---------------------------
1. ElasticSearch 8.11.3         - Search and analytics engine
2. Kibana 8.11.3                - ElasticSearch web interface
3. Logstash 8.11.3              - Data processing pipeline
4. APM Server 8.10.4            - Application performance monitoring
5. Apache APISIX 3.7.0          - API gateway and load balancer
6. APISIX Dashboard 3.0.1       - APISIX web interface
7. etcd v3.5.9                  - APISIX configuration storage
8. Prometheus v2.48.0           - Metrics collection
9. Grafana 10.2.2               - Metrics visualization
10. curl (latest)               - Utility for setup scripts

IMAGES NOT INCLUDED (optional monitoring components)
----------------------------------------------------
- prom/alertmanager:v0.26.0
- quay.io/prometheuscommunity/elasticsearch-exporter:v1.6.0

These are optional components for advanced monitoring and can be pulled
separately if needed on the target machine.


IMPORT INSTRUCTIONS
===================

Windows:
--------
1. Copy elk-stack-all-images.tar to target machine
2. Open Command Prompt or PowerShell
3. Run:
   docker load -i elk-stack-all-images.tar

4. Verify import:
   docker images

Linux/Mac:
----------
1. Copy elk-stack-all-images.tar to target machine
2. Open terminal
3. Run:
   docker load -i elk-stack-all-images.tar

4. Verify import:
   docker images


NEXT STEPS AFTER IMPORT
========================

1. Create Docker Networks:
   docker network create --driver bridge --subnet 172.42.0.0/16 ce-base-micronet
   docker network create ce-base-network

2. Configure Environment:
   Windows: copy .env.example .env && config\scripts\setup\generate-secrets.bat
   Linux:   cp .env.example .env && ./config/scripts/setup/generate-secrets.sh

3. Start Services:
   docker-compose up -d

4. Check Status (wait for all services to be healthy):
   docker-compose ps

5. Access Services:
   - Kibana:           http://localhost:9080/kibana
   - APISIX Dashboard: http://localhost:9000 (admin/admin)
   - Grafana:          http://localhost:9080/grafana
   - Prometheus:       http://localhost:9080/prometheus

6. Verify ElasticSearch:
   curl http://localhost:9080/elasticsearch/_cluster/health?pretty


OPTIONAL: PULL MISSING IMAGES
==============================

If you need the optional monitoring components:

docker pull prom/alertmanager:v0.26.0
docker pull quay.io/prometheuscommunity/elasticsearch-exporter:v1.6.0


TROUBLESHOOTING
===============

Problem: "Cannot connect to Docker daemon"
Solution: Ensure Docker is running
  Windows: Start Docker Desktop
  Linux:   sudo systemctl start docker

Problem: "Error loading image"
Solution: Verify file integrity
  - Check file size (should be ~1.9 GB)
  - Re-copy if file is corrupt
  - Ensure sufficient disk space

Problem: Services failing to start
Solution:
  - Verify all images loaded: docker images
  - Check networks exist: docker network ls
  - Review logs: docker-compose logs [service-name]


SINGLE ARCHIVE vs SEPARATE FILES
=================================

Single Archive (this method):
  Pros:  - One file to transfer
         - Simpler management
  Cons:  - Large file (~1.9 GB)
         - All-or-nothing import
         - Must re-transfer entire file if corrupt

Separate Archives (standard export-images.bat):
  Pros:  - Resume if one file fails
         - Transfer in batches
         - Individual file verification
  Cons:  - Multiple files to manage
         - More complex


SUPPORT
=======

For complete documentation, see:
- docs/DOCKER_IMAGES_EXPORT.md
- docs/SETUP.md
- CLAUDE.md
