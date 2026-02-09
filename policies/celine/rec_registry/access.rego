# Example policy for rec-registry service
# Save as: policies/celine/rec_registry/access.rego

package celine.rec_registry.access

import rego.v1

import data.celine.scopes

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
    scopes.has_scope("rec_registry.admin")
}

reason := "admin access granted" if {
    input.action.name == "admin"
    scopes.has_scope("rec_registry.admin")
}

# Import action - requires rec_registry.import scope
allow if {
    input.action.name == "import"
    scopes.has_scope("rec_registry.import")
}

reason := "import access granted" if {
    input.action.name == "import"
    scopes.has_scope("rec_registry.import")
}

# Export action - requires rec_registry.export scope
allow if {
    input.action.name == "export"
    scopes.has_scope("rec_registry.export")
}

reason := "export access granted" if {
    input.action.name == "export"
    scopes.has_scope("rec_registry.export")
}

# Super admin - rec_registry.admin wildcard matches all
allow if {
    scopes.has_scope("rec_registry.*")
}

reason := "super admin access granted" if {
    scopes.has_scope("rec_registry.*")
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
    scopes.is_anonymous
}
