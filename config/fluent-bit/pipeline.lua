-- Per-event processing for fluent-bit.conf (Lua filter). Return codes: -1 drop, 1 record + timestamp changed.
local TOKEN = os.getenv("LOG_INGEST_TOKEN") or ""

function process(tag, ts, record)
    -- only events carrying the shared token get in (CloudHub reaches this port from the internet)
    if TOKEN == "" or record["auth_token"] ~= TOKEN then
        return -1, ts, record
    end
    record["auth_token"] = nil

    -- tenant_id: letters, digits, "_" and "-", lowercase; missing -> unknown (OpenSearch DLS filters on it)
    local t = record["tenant_id"]
    if t == nil or t == "" then
        record["tenant_id"] = "unknown"
    else
        t = tostring(t)
        if #t < 2 or #t > 50 or not t:match("^[%w_%-]+$") then
            record["tenant_id_original"] = t
            t = t:gsub("[^%w_%-]", "")
        end
        record["tenant_id"] = t:lower()
    end

    -- event time from log4j (JsonLayout "instant", or "timeMillis"), else keep the receive time
    local inst = record["instant"]
    if type(inst) == "table" and inst["epochSecond"] then
        ts = inst["epochSecond"] + (inst["nanoOfSecond"] or 0) / 1e9
    elseif tonumber(record["timeMillis"]) then
        ts = tonumber(record["timeMillis"]) / 1000
    end

    if record["host"] ~= nil then
        record["source_host"] = record["host"]
        record["host"] = nil
    end
    record["timeMillis"], record["endOfBatch"], record["loggerFqcn"] = nil, nil, nil

    record["route"] = (record["log_type"] == "mule" or record["application"] ~= nil) and "mule" or "other"
    return 1, ts, record
end
