import '../config/troika_config.dart';

/// One request's owner, origin and conversation, including an identity revision.
/// Access-token rotation for the same identity does not invalidate the request.
class TroikaRequestIdentity {
  TroikaRequestIdentity({String? conversationId})
    : revision = TroikaConfig.voiceIdentityRevision,
      owner = TroikaConfig.accountEmail,
      origin = TroikaConfig.serverUrl,
      _homeSession = TroikaConfig.sessionId,
      _homeSessionKey = TroikaConfig.sessionKey,
      session = conversationId ?? TroikaConfig.sessionId,
      sessionKey = conversationId ?? TroikaConfig.sessionKey,
      _hosted = TroikaConfig.signedIn;

  final int revision;
  final String owner, origin, session, sessionKey;
  final String _homeSession, _homeSessionKey;
  final bool _hosted;

  bool matches(TroikaRequestIdentity other) =>
      revision == other.revision &&
      owner == other.owner &&
      origin == other.origin &&
      session == other.session &&
      sessionKey == other.sessionKey &&
      _hosted == other._hosted;

  void check() {
    if (revision != TroikaConfig.voiceIdentityRevision ||
        owner != TroikaConfig.accountEmail ||
        origin != TroikaConfig.serverUrl ||
        _homeSession != TroikaConfig.sessionId ||
        _homeSessionKey != TroikaConfig.sessionKey ||
        (_hosted && !TroikaConfig.voiceSessionAvailable)) {
      throw const RequestIdentityChanged();
    }
  }

  Uri uri(String path) {
    check();
    return Uri.parse('$origin$path');
  }

  Map<String, String> headers([Map<String, String> extra = const {}]) {
    check();
    return {...extra, ...TroikaConfig.headers};
  }

  Map<String, String> chatHeaders(Map<String, String> extra) => {
    ...headers(extra),
    'X-Hermes-Session-Key': sessionKey,
    'X-Hermes-Session-Id': session,
  };
}

class RequestIdentityChanged implements Exception {
  const RequestIdentityChanged();
  @override
  String toString() => 'The request identity changed.';
}
