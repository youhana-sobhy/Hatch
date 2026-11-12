# Golden template library

One directory per **vendor × role**, plus shared variable layers and the device catalog.
Changes here are production configuration: they are reviewed by the owning team and CI
test-renders every template against the security baseline (`hatchctl templates lint`).

| Template | Owner | Day-0 |
|---|---|---|
| `nxos/leaf` | dc-network-platform | POAP |
| `nxos/border` | dc-network-platform | POAP |
| `fortios/edge-fw` | security-engineering | bootstrap + call-home action |
| `junos/pe-router` | ip-core | ZTP config + op-script |
| `panos/dc-fw` | security-engineering | `init-cfg.txt` |
| `esxi/compute-host` | cloud-infrastructure | kickstart |

Authoring guide: [docs/templates.md](../docs/templates.md).
