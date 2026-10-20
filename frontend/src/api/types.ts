import type { components } from './schema';

// Wire types come from Alexey's A-01 OpenAPI, without a second manual schema.
export type User = components['schemas']['UserOut'];
export type Membership = components['schemas']['MembershipOut'];
export type Company = components['schemas']['CompanyOut'];
export type Me = components['schemas']['MeOut'];
export type Credentials = components['schemas']['LoginCredentials'];
export type Registration = components['schemas']['Credentials'];
export type ApiErrorBody = components['schemas']['ErrorOut'];
export type FeedItem = components['schemas']['FeedItem'];
export type Feed = components['schemas']['FeedOut'];
export type Claim = components['schemas']['Claim'];
export type Evidence = components['schemas']['EvidenceOut'];
export type InsightResult = components['schemas']['InsightResult'];
export type Insight = components['schemas']['InsightOut'];
export type Chat = components['schemas']['ChatOut'];
export type Message = components['schemas']['MessageOut'];
export type Job = components['schemas']['JobOut'];
export type AdminStats = components['schemas']['StatsOut'];
