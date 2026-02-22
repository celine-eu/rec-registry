# Fixed REC Registry Access Policy
# Save as: policies/celine/rec_registry/access.rego

package celine.rec_registry.access

import rego.v1

# =============================================================================
# REC REGISTRY AUTHORIZATION
# =============================================================================
#
# Rules:
# - Users can access /me* endpoints (handled by middleware, not policy)
# - Admin actions require specific scopes
# - Import/export require elevated permissions
#
# =============================================================================

default allow := false
default reason := "unauthorized"

# =============================================================================
# ADMIN ACTIONS
# =============================================================================

# Generic admin access - requires rec-registry.admin scope
allow if {
    input.action.name == "admin"
    data.celine.scopes.has_scope("rec-registry.admin")
}

# Import action - requires rec-registry.import OR rec-registry.admin
allow if {
    input.action.name == "import"
    data.celine.scopes.has_any_scope(["rec-registry.import", "rec-registry.admin"])
}

# Export action - requires rec-registry.export OR rec-registry.admin
allow if {
    input.action.name == "export"
    data.celine.scopes.has_any_scope(["rec-registry.export", "rec-registry.admin"])
}

# Lookup action - requires rec-registry.lookup OR rec-registry.admin
allow if {
    input.action.name == "lookup"
    data.celine.scopes.has_any_scope(["rec-registry.lookup", "rec-registry.admin"])
}

# =============================================================================
# REASON - Use else chain to avoid conflicts
# =============================================================================

reason := "admin access granted" if {
    allow
    input.action.name == "admin"
} else := "import access granted" if {
    allow
    input.action.name == "import"
} else := "export access granted" if {
    allow
    input.action.name == "export"
} else := "lookup access granted" if {
    allow
    input.action.name == "lookup"
} else := "access granted" if {
    allow
}

# =============================================================================
# DENIAL REASONS
# =============================================================================

reason := "missing required scope" if {
    not allow
    input.subject.type == "user"
}

reason := "authentication required" if {
    not allow
    data.celine.scopes.is_anonymous
}
