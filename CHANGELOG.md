# CHANGELOG

<!-- version list -->

## v1.6.0 (2026-10-08)

### Bug Fixes

- Cap sensors list to 500. closes #37
  ([`3905dcd`](https://github.com/celine-eu/rec-registry/commit/3905dcd667dad17a95c2e666fe1ca7761fc6b1dd))

- Cleanup refs
  ([`49bdf7f`](https://github.com/celine-eu/rec-registry/commit/49bdf7fd77d044f08c7b3fa559f7f83b9f9be650))

- Correct rego ref, closes #42
  ([`01539c5`](https://github.com/celine-eu/rec-registry/commit/01539c5f2565f2414cf60eae70eb5ace5c1b96c1))

- Remove nested extra, closes #41
  ([`b13e00a`](https://github.com/celine-eu/rec-registry/commit/b13e00aec4457d6ca983b7bd562dfca0bb008782))

- Retry on create/replace of assets
  ([`38a529f`](https://github.com/celine-eu/rec-registry/commit/38a529f127c5b16849b99f01c508b32549dabc72))

- Review alembic index, review tests. closes #39
  ([`489b9e4`](https://github.com/celine-eu/rec-registry/commit/489b9e4c001120288b4dc4d771d326c7134f96fe))

- Review uniqueness index, fail with 409 on duplicates. closes #40
  ([`d0f7cbb`](https://github.com/celine-eu/rec-registry/commit/d0f7cbbe115cc3a879fff4a514acdc05ec64a7ab))

- Review version handling, expose correct schema version. Closes #38
  ([`6ee80aa`](https://github.com/celine-eu/rec-registry/commit/6ee80aaf76019a5dc23a605252ae71569e137444))

### Chores

- Drop the celine-sdk release TODOs now that 2.0.0 ships them
  ([`35f0003`](https://github.com/celine-eu/rec-registry/commit/35f0003330ad154557d848e553625357120518f7))

- Fix workflow
  ([`1cee388`](https://github.com/celine-eu/rec-registry/commit/1cee388d66ff43c6b1e205f23a0076981766d7c7))

- Update harness
  ([`daa3147`](https://github.com/celine-eu/rec-registry/commit/daa3147f3165a918c7b23143f1ff3bd6060453c5))

- Upgrade celine-sdk to 2.0.0
  ([`32682dc`](https://github.com/celine-eu/rec-registry/commit/32682dc2147573ec4a592aceeb57e3670f7199a9))

### Features

- Add bulk lookup
  ([`d3ea3a7`](https://github.com/celine-eu/rec-registry/commit/d3ea3a7e808c9f7155c3e23bf13137e1447ce5b3))

- Add crud api, add tests
  ([`2e8e1b1`](https://github.com/celine-eu/rec-registry/commit/2e8e1b1cf6a9a668bb5aa83ff9cdabe85292e2c5))

- Add DID field, add v0.6 specs
  ([`3bab32c`](https://github.com/celine-eu/rec-registry/commit/3bab32c627c04bc80a92a45d5b4eb63c7b87d79a))

- Add editing to regisrty properties
  ([`1f424ef`](https://github.com/celine-eu/rec-registry/commit/1f424ef3e6850fb385abcdc02347353492718cf2))

- Add meter association, area association
  ([`f840a0c`](https://github.com/celine-eu/rec-registry/commit/f840a0c5cedf646633b70d1be007b2be1a555d9b))

- Extend area mapping
  ([`1540ff6`](https://github.com/celine-eu/rec-registry/commit/1540ff6a05a01d31e59b865ef2696126baba68f9))

- Grant member writes per field; one active holder per POD
  ([`c49d425`](https://github.com/celine-eu/rec-registry/commit/c49d4250fd5b9c484b1814e2f4a36a3c34c0fed4))

- Hold a meter's POD like a delivery point, answer self-service from the active member only, and
  hold DIDs unique among active members, answer cross-community lookups from the active member only
  ([`2cf0e63`](https://github.com/celine-eu/rec-registry/commit/2cf0e6337df4540095ff2171edcf7ef49bb126a3))

- Name the route and community on refusals recorded before routing, and keep member keys out of the
  access log
  ([`727a321`](https://github.com/celine-eu/rec-registry/commit/727a321eb8829049d4ded6ff2b827dc60cce1cc2))

- Read community shared delivery points
  ([`da6c54d`](https://github.com/celine-eu/rec-registry/commit/da6c54da9de3d643ec1610fc8ddcd288ce515fda))

- Record admin and self-service refusals on celine.audit, gate API docs outside dev
  ([`9bbee6b`](https://github.com/celine-eu/rec-registry/commit/9bbee6b7277691400a1c3ecf683b0ddcccd1c264))

- Update schema, update example refs
  ([`9d7cc99`](https://github.com/celine-eu/rec-registry/commit/9d7cc991695a94576b80716a2dfa382dcf371f2c))


## v1.5.0 (2026-07-02)

### Bug Fixes

- Externalize local settings
  ([`d754c60`](https://github.com/celine-eu/rec-registry/commit/d754c602d7642988c6054f400a720fba94172b96))

### Chores

- Update docs
  ([`21d5cf3`](https://github.com/celine-eu/rec-registry/commit/21d5cf323992d3a02ab616347ec132ab10df16c2))

- Upgrade celine-sdk to 1.11.0
  ([`9a38888`](https://github.com/celine-eu/rec-registry/commit/9a388884c54465ac04bf6edbe2afcd8b7336539f))

- Upgrade celine-sdk to 1.12.0
  ([`611d54c`](https://github.com/celine-eu/rec-registry/commit/611d54ce28c56af936a5d768f1f7c3642c5662a2))

- Upgrade celine-sdk to 1.12.1
  ([`4db4934`](https://github.com/celine-eu/rec-registry/commit/4db493419e9fa0ee4c6e4acebafed9ccd43fcd3d))

- Upgrade celine-sdk to 1.13.0
  ([`c3d6067`](https://github.com/celine-eu/rec-registry/commit/c3d6067ae4c9b8d3304869ca567f6f9008b5661c))

- **deps**: Bump fastapi from 0.128.0 to 0.136.1
  ([`07c4f72`](https://github.com/celine-eu/rec-registry/commit/07c4f7221da3f7d3c957a40142d741905a8b8295))

- **deps**: Bump pydantic-settings from 2.12.0 to 2.13.1
  ([`0567ed9`](https://github.com/celine-eu/rec-registry/commit/0567ed97b3f242b6c0dc011b13709651a7182b6f))

- **deps**: Bump sqlalchemy
  ([`2b30666`](https://github.com/celine-eu/rec-registry/commit/2b30666b1d66b1cd7cb524dec28a795e75e3c5f8))

- **deps**: Bump the runtime-dependencies group across 1 directory with 2 updates
  ([`4db321c`](https://github.com/celine-eu/rec-registry/commit/4db321c8fdb75798f064c3c9c0a4a4260b211964))

- **deps-dev**: Bump pytest
  ([`a66aef4`](https://github.com/celine-eu/rec-registry/commit/a66aef4bb28759c0deeb766c459466616ff553f6))

### Continuous Integration

- Bump hynek/build-and-inspect-python-package
  ([`c54d93a`](https://github.com/celine-eu/rec-registry/commit/c54d93aceb7ce7a0e89c626514f17a60e2805094))

### Features

- Use sdk group extraction
  ([`793217f`](https://github.com/celine-eu/rec-registry/commit/793217feab92bbde3f92a22d75da643e8bd5d43c))


## v1.4.0 (2026-04-16)

### Bug Fixes

- Update rec mappings
  ([`65a4fb2`](https://github.com/celine-eu/rec-registry/commit/65a4fb2992e8aefa00190d020467b0076e85817a))

### Chores

- Add tests
  ([`dc447cb`](https://github.com/celine-eu/rec-registry/commit/dc447cba60a2abd2d7250fa3ecd6412a421627d1))

- Update example yaml
  ([`ee3d331`](https://github.com/celine-eu/rec-registry/commit/ee3d3314c1e5583c6c0ef3eff6da2a65ee5cfc3f))

- Upgrade celine-sdk to 1.10.0
  ([`598032a`](https://github.com/celine-eu/rec-registry/commit/598032afed78f7dd9c65649b1fdf131721195af3))

- Upgrade celine-sdk to 1.7.0
  ([`00e538c`](https://github.com/celine-eu/rec-registry/commit/00e538cb0f28702574fa37acd23eb762a15283c6))

- Upgrade celine-sdk to 1.8.0
  ([`90b51c5`](https://github.com/celine-eu/rec-registry/commit/90b51c57792548fa358df55d335615da9f517efe))

- Upgrade celine-sdk to 1.9.0
  ([`ed67934`](https://github.com/celine-eu/rec-registry/commit/ed67934851412ce3d095a59cd5e4090d1b1ea175))

### Features

- Review import/export to support multiple REC. update to v0.5 schema
  ([`04c389f`](https://github.com/celine-eu/rec-registry/commit/04c389ff8332a784f9d76b5c6707074a7a0dcb10))

- Upgrade schema to v0.5
  ([`c508886`](https://github.com/celine-eu/rec-registry/commit/c50888667cec520d29f4287778324534882cce11))


## v1.3.4 (2026-04-08)

### Bug Fixes

- Support for areas geometry and metadata
  ([`fd7566b`](https://github.com/celine-eu/rec-registry/commit/fd7566b0f469afcfe39896c2c937b04bf84471a9))

### Chores

- Upgrade celine-sdk to 1.5.0
  ([`60cc769`](https://github.com/celine-eu/rec-registry/commit/60cc76971ab63775b32b618ffeca58f913e0d7d1))

- Upgrade celine-sdk to 1.6.0
  ([`0697477`](https://github.com/celine-eu/rec-registry/commit/06974771e4cf687fb29fedc990a4efb443192d91))

- **deps**: Bump the runtime-dependencies group across 1 directory with 3 updates
  ([`6130168`](https://github.com/celine-eu/rec-registry/commit/61301681744d2b8e706dcb29dbbc9cd4ab63d263))

- **deps-dev**: Bump debugpy
  ([`9d0bdb4`](https://github.com/celine-eu/rec-registry/commit/9d0bdb4c507276cde17971b469eebc78914f9909))

### Continuous Integration

- Bump the actions group across 1 directory with 3 updates
  ([`52f15bd`](https://github.com/celine-eu/rec-registry/commit/52f15bdfad487f24cc2806fafedaf67db7aaaa6f))


## v1.3.3 (2026-03-23)

### Bug Fixes

- Handle user path for user jwt
  ([`af39977`](https://github.com/celine-eu/rec-registry/commit/af399778e677cb7702786d5ca2030de3c3827575))

### Chores

- Upgrade celine-sdk to 1.4.3
  ([`39b76b5`](https://github.com/celine-eu/rec-registry/commit/39b76b5df1b5144b8e2a554abebcb3778908beb2))


## v1.3.2 (2026-03-03)

### Bug Fixes

- Expose envvar
  ([`5ff6435`](https://github.com/celine-eu/rec-registry/commit/5ff643513b3bcb27aadb1e3ce53052d7a1f428a5))


## v1.3.1 (2026-03-02)

### Bug Fixes

- Upgrade sdk with new methods
  ([`4200783`](https://github.com/celine-eu/rec-registry/commit/42007839b6897a8df3ec3c6f9940dac0d064d86d))

- Use get_username() not sub for identifier
  ([`4f68d5b`](https://github.com/celine-eu/rec-registry/commit/4f68d5b62ed209fbce8df37cff59220b2cb6edb3))

### Chores

- Rm dumpster cli
  ([`cca3f65`](https://github.com/celine-eu/rec-registry/commit/cca3f6510da39193cdbb45627db54e54aea9e4fe))


## v1.3.0 (2026-02-28)

### Features

- Add verify_ssl flag
  ([`e28d0b8`](https://github.com/celine-eu/rec-registry/commit/e28d0b8a1305a1f87b78f92c0639f3d77239fd0e))


## v1.2.0 (2026-02-27)

### Features

- Fix image for deployment
  ([`67f19cc`](https://github.com/celine-eu/rec-registry/commit/67f19cc546e3bc33f8cb6deccb621f639487bf5b))


## v1.1.4 (2026-02-26)

### Bug Fixes

- Hatch false positive
  ([`066e57d`](https://github.com/celine-eu/rec-registry/commit/066e57d41cd55b4ff00cadf451c0a6b82366b5af))


## v1.1.3 (2026-02-26)

### Bug Fixes

- Use hatch for build
  ([`df8e088`](https://github.com/celine-eu/rec-registry/commit/df8e0887a2e2d7ab1d5662365fb881a863fe8ed8))


## v1.1.2 (2026-02-26)

### Bug Fixes

- Use hatch for build
  ([`f7a1f1a`](https://github.com/celine-eu/rec-registry/commit/f7a1f1ac4e13716f1055a8abc55363debaddad5f))

### Chores

- Use local venv
  ([`18a427a`](https://github.com/celine-eu/rec-registry/commit/18a427a251bc2de0d074b6d3fa55ed895ae64319))


## v1.1.1 (2026-02-26)

### Bug Fixes

- Use local venv
  ([`27fef74`](https://github.com/celine-eu/rec-registry/commit/27fef7426f0c0908987704f7f2d95c2db8857818))


## v1.1.0 (2026-02-25)

### Bug Fixes

- Default dev refs
  ([`d25600d`](https://github.com/celine-eu/rec-registry/commit/d25600d73992d15a316628d9626de51b224f4aeb))

- Review docker setup
  ([`f9e627b`](https://github.com/celine-eu/rec-registry/commit/f9e627b3ae773bae5abd56dc6bc874c2b8dabe52))

- Taskfile run cmd
  ([`0f6e13d`](https://github.com/celine-eu/rec-registry/commit/0f6e13d913058823d43193e32b2bcf8a1a816875))

- Update access rego
  ([`1471855`](https://github.com/celine-eu/rec-registry/commit/1471855c9262a7aeec1ca6bd4e82b16a73f822e5))

### Chores

- Add docker build
  ([`eb9c2dc`](https://github.com/celine-eu/rec-registry/commit/eb9c2dc0b39ce8e96f93a6c8e62ecc65083f4e5f))

- Add pkg permissions
  ([`56372d9`](https://github.com/celine-eu/rec-registry/commit/56372d9b3120bda6859c043917d75eec3d88667b))

- Add task import example rec
  ([`39345e3`](https://github.com/celine-eu/rec-registry/commit/39345e3cc25a149ec5645f7877c457b38858290a))

- Expose ports
  ([`056a5a0`](https://github.com/celine-eu/rec-registry/commit/056a5a01b994f05a878861c19519e6aa9e52c092))

- Fix schema mapping
  ([`776a610`](https://github.com/celine-eu/rec-registry/commit/776a610ee4da3d8cf9c624ded0ac6943b5306039))

- Move to src
  ([`8311e75`](https://github.com/celine-eu/rec-registry/commit/8311e7599332a12681e96057b7469407b5afc3c5))

- Refactor, add lookups, adapt model
  ([`10ffe70`](https://github.com/celine-eu/rec-registry/commit/10ffe7057cde2e2d95ebf30badf3f7777d5b9847))

- Review docker setup
  ([`c80702a`](https://github.com/celine-eu/rec-registry/commit/c80702ada07453968daecd02ad8ce770869005a0))

- Run uvcorn from venv
  ([`0a4a381`](https://github.com/celine-eu/rec-registry/commit/0a4a3815406579b73a04b80f6960f4cb5fb23df8))

- Up debugger config
  ([`48b8834`](https://github.com/celine-eu/rec-registry/commit/48b8834d40b799d1b1783713f9c0716c07c6719f))

- Upgrade celine-sdk
  ([`9f9ee91`](https://github.com/celine-eu/rec-registry/commit/9f9ee91d1b89690cf871bc3bb4f7f097845771b9))

- Upgrade celine-sdk
  ([`341022e`](https://github.com/celine-eu/rec-registry/commit/341022ee5a2a0b553e11b2f1cf7122fe5ab0c14b))

- Upgrade taskfile
  ([`8c47262`](https://github.com/celine-eu/rec-registry/commit/8c4726243421623324f4f6cb74e16e6e1dde621a))

### Documentation

- Add example rec definition
  ([`45fa67c`](https://github.com/celine-eu/rec-registry/commit/45fa67c5009176fde6cdd30934a07c827fdc47db))

### Features

- Add auth middleware from sdk
  ([`dd4124d`](https://github.com/celine-eu/rec-registry/commit/dd4124dd45fa53fab8b81be3f3aaaca7d1bd1409))

- Add integrated policies
  ([`29a8612`](https://github.com/celine-eu/rec-registry/commit/29a86126c26dfeae6f291ff98331f7c567a28ec4))

- Correct scope definition
  ([`33be411`](https://github.com/celine-eu/rec-registry/commit/33be41139ed90868dceea17c56006b0b44cb6900))

- Refactor
  ([`70150dd`](https://github.com/celine-eu/rec-registry/commit/70150dd5f0b0153400f735d25242c7a407230d38))

- Review policy
  ([`4cdfb1b`](https://github.com/celine-eu/rec-registry/commit/4cdfb1b1d92b142d9213b2f78cc3cd0a96045b55))

- Typed response from api
  ([`079683b`](https://github.com/celine-eu/rec-registry/commit/079683bb858d2d57c2c0dbdefdd769785bee7d9d))

- Use oidc settings and audience for jwt token checks
  ([`3956abd`](https://github.com/celine-eu/rec-registry/commit/3956abd3b25d7a603ece988a2ad26ea822fab6f3))


## v1.0.0 (2026-01-23)

- Initial Release
