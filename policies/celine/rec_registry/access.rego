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

# Generic admin access - requires rec_registry.admin scope
allow if {
    input.action.name == "admin"
    data.celine.scopes.has_scope("rec_registry.admin")
}

# Import action - requires rec_registry.import OR rec_registry.admin
allow if {
    input.action.name == "import"
    data.celine.scopes.has_any_scope(["rec_registry.import", "rec_registry.admin"])
}

# Export action - requires rec_registry.export OR rec_registry.admin
allow if {
    input.action.name == "export"
    data.celine.scopes.has_any_scope(["rec_registry.export", "rec_registry.admin"])
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
