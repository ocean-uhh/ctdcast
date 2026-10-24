.. _registries:

==========
Registries
==========

A cruise config names three things by slug or code — institutions, a platform, and
contributor roles. The valid values ship inside the installed package, so rather than
open a YAML file in ``site-packages`` to find one, list them:

.. code-block:: bash

   ctdcast list                              # the three registries
   ctdcast list institutions                 # what ships + your user directory
   ctdcast list institutions config.yaml     # ... plus what this config adds
   ctdcast list platforms --search meteor    # filter by slug or name
   ctdcast list roles --vocabulary W08        # one role vocabulary

The full command reference is in :doc:`cli_reference`. What each registry is, and how to
add to it without editing package data, follows.

Institutions
============

Research organisations, referenced by ``cruise_info.institutions`` (see
:doc:`cruise_metadata`). They resolve from four sources, later winning slug by slug — the
``Source`` column in ``ctdcast list institutions`` tells you which supplied each entry:

1. **packaged** — the shipped ``ctdcast/config/institutions.yaml``;
2. **user** — ``~/.config/ctdcast/institutions.yaml`` (or ``$CTDCAST_CONFIG_DIR``), for
   organisations you use across cruises;
3. a **config file** named by ``cruise_info.institutions_file``, kept beside the cruise
   config;
4. **inline** — an entry in ``cruise_info.institutions`` written with its own ``name`` and
   ``id``, which needs no registry at all.

Tiers 3 and 4 are only visible when you pass the config, so ``ctdcast list institutions``
with no config prints a footer saying so.

Platforms
=========

Vessels, referenced by ``cruise_info.platform`` (or the older ``ship_slug``). The platform
drives the EXPOCODE via its ICES code, so a wrong slug is refused rather than guessed.
Two sources:

1. **packaged** — the shipped ``ctdcast/config/platforms.yaml``;
2. **inline** — ``cruise_info.platform`` written as a mapping, for a vessel not in the
   shared registry:

   .. code-block:: yaml

      cruise_info:
        platform:
          name: "RRS Discovery"
          ices_code: "74E3"        # drives the EXPOCODE
          platform: "..."          # optional L06 category

   This works end to end — no need to edit ``platforms.yaml``.

``ctdcast list platforms`` also prints two sets of **traps** that ``platforms.yaml``
records and the resolver refuses: ``ambiguous_slugs`` (a name shared by several hulls —
``meteor`` alone is refused; use ``meteor3``) and ``forbidden_codes`` (ICES codes that must
not be used, each with the reason). They are shown so you can see *why* a slug is refused,
not only that it was.

Roles
=====

Contributor role codes, referenced by ``cruise_info.role_vocabulary`` (people) and
``cruise_info.institution_role_vocabulary`` (institutions). There are four vocabularies on
two axes:

- **Person roles** — ``C89`` (BODC dataset roles, the default) and ``G04``;
- **Institution roles** — ``C59`` (the default) and ``W08``.

``ctdcast list roles`` groups them by axis and marks each axis's default, so a person role
is never mistaken for one usable where an institution role is required. ``--vocabulary``
shows a single one.
