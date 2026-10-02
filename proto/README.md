# Official Upstox V3 protobuf required for T01

Provision the official `MarketDataFeedV3.proto` and its generated Python classes,
or the official SDK's generated V3 classes, in the environment setup. Record
source/version/checksum when supplied. Cloud tasks must not fetch them, invent a
schema, or call a JSON stream a V3 protobuf simulator.

Provisioned on 2026-10-02 by the owner-authorized pip install: Upstox SDK 2.30.0
supplies `upstox_client.feeder.proto.MarketDataFeedV3_pb2`. Its V3 FeedResponse
imports successfully. T01 should use these official generated classes. No
separate source download is necessary.
