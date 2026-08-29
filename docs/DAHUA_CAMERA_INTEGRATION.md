# Dahua / ONVIF camera integration

Ai.WAGVID uses a provider-neutral camera contract. Dahua support is an adapter,
not a dependency of analysis or scoring code. Capability snapshots are discovered
per exact model and firmware; the product never assumes every Dahua camera supports
PTZ, presets, analytics, auto tracking or edge recording.

The portable control plane prioritizes ONVIF Profile T for modern streaming/PTZ,
Profile G for edge recording/retrieval and Profile M for analytics metadata/events.
Profile S is compatibility-only. Documented Dahua API extensions may add native
tracking and vendor events. Optional native SDK work must remain isolated.

Safety rules:

- exactly one of operator, camera-native tracking or Ai.WAGVID may own PTZ;
- local emergency stop always releases ownership and disables native tracking;
- camera human/motion events are acquisition hints, never athlete identity or score facts;
- low-confidence assisted tracking stops/holds instead of hunting;
- pan, tilt and zoom commands are bounded by the configured capture policy;
- canonical capture uses a discovered high-quality stream, even when preview/tracking uses a substream;
- a static calibration is valid only at its bound preset/PTZ/zoom state and tolerance;
- moving-PTZ floor captures must mark fixed-world boundary measurements unavailable unless dynamic calibration has been empirically validated;
- every capture records time-aligned PTZ/tracking provenance and reconnect/quality events.

The adapter is tested with injected gateways. Hardware promotion still requires an
exact camera/firmware compatibility probe, credential/TLS review, stream capture,
clock-drift measurement, PTZ stop testing and recovery from network loss.
