-- Shadows APISIX's apisix/control/v1.lua (config.yaml extra_lua_path) to fix /v1/routes, /v1/route/<id>,
-- /v1/upstreams and /v1/upstream/<id> returning 500 "Cannot serialise, excessive nesting".
-- Cause: once a hostname node is DNS-resolved (every node here is a container name) or an upstream is
-- health-checked, APISIX keeps back-references to the parent object (route.dns_value.upstream.parent,
-- upstream.dns_value.parent, upstream.checker_upstream.parent); the stock dump only unlinks
-- value.upstream.parent, so cjson hits the cycle. Still the case in 3.13.
-- ponytail: wraps the stock handlers by URI; drop this file (and extra_lua_path) when APISIX fixes it.
local routes = dofile("/usr/local/apisix/apisix/control/v1.lua")

local function unlink(item)
    if type(item) ~= "table" then
        return
    end
    item.checker, item.checker_upstream, item.checker_idx, item.clean_handlers = nil, nil, nil, nil
    local dns = item.dns_value
    if dns then
        dns.parent = nil
        if dns.upstream then
            dns.upstream.parent = nil
        end
    end
end

local dumps = {["/routes"] = true, ["/route/*"] = true, ["/upstreams"] = true, ["/upstream/*"] = true}
for _, route in ipairs(routes) do
    if dumps[route.uris[1]] then
        local handler = route.handler
        route.handler = function(...)
            local code, body = handler(...)
            if code == 200 and type(body) == "table" then
                if body[1] then
                    for _, item in ipairs(body) do
                        unlink(item)
                    end
                else
                    unlink(body)
                end
            end
            return code, body
        end
    end
end

return routes
