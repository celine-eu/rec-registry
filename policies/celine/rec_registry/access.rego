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
# Actions are named by the middleware from the path AND the HTTP method, so
# reading a community and rewriting its members are separate permissions. A
# service that creates members should not thereby be able to read every
# community, nor a reporting client be able to write.
#
# `rec-registry.admin` satisfies all of these through the shared matcher's
# admin-override rule ({service}.admin covers {service}.*), so an existing
# admin token keeps working unchanged.
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

# Read any admin view - requires rec-registry.read OR rec-registry.admin
allow if {
    input.action.name == "read"
    data.celine.scopes.has_any_scope(["rec-registry.read", "rec-registry.admin"])
}

# Create/update members - the runtime write an onboarding service performs
allow if {
    input.action.name == "members.write"
    data.celine.scopes.has_any_scope([
        "rec-registry.members.write",
        "rec-registry.admin",
    ])
}

# Create/update assets and their delivery points
allow if {
    input.action.name == "assets.write"
    data.celine.scopes.has_any_scope([
        "rec-registry.assets.write",
        "rec-registry.admin",
    ])
}

# Community metadata, areas and topology
allow if {
    input.action.name == "community.write"
    data.celine.scopes.has_any_scope([
        "rec-registry.community.write",
        "rec-registry.admin",
    ])
}

# Permanent erasure of a member and its assets. Separate from members.write on
# purpose: deactivating somebody is recoverable, removing them is not, and the
# two should not be grantable together by accident.
allow if {
    input.action.name == "members.purge"
    data.celine.scopes.has_any_scope([
        "rec-registry.members.purge",
        "rec-registry.admin",
    ])
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

# Asset lookup by owner - enumerates what named members own, so it is named
# apart from `lookup` even though the same scopes grant it today. Splitting the
# grant later is then a policy change, not an API change.
allow if {
    input.action.name == "assets.lookup"
    data.celine.scopes.has_any_scope(["rec-registry.lookup", "rec-registry.admin"])
}

# =============================================================================
# REASON - Use else chain to avoid conflicts
# =============================================================================

reason := "admin access granted" if {
    allow
    input.action.name == "admin"
} else := "read access granted" if {
    allow
    input.action.name == "read"
} else := "member write access granted" if {
    allow
    input.action.name == "members.write"
} else := "member purge access granted" if {
    allow
    input.action.name == "members.purge"
} else := "asset write access granted" if {
    allow
    input.action.name == "assets.write"
} else := "community write access granted" if {
    allow
    input.action.name == "community.write"
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
