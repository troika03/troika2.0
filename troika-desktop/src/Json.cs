using System;
using System.Collections;
using System.Collections.Generic;
using System.Globalization;
using System.Web.Script.Serialization;

namespace Troika.Desktop {
    public static class Json {
        public static string Encode(object value) { return new JavaScriptSerializer { MaxJsonLength = 4 * 1024 * 1024 }.Serialize(value); }
        public static Dictionary<string, object> Parse(string text) {
            return new JavaScriptSerializer { MaxJsonLength = 4 * 1024 * 1024 }.DeserializeObject(text) as Dictionary<string, object> ?? new Dictionary<string, object>();
        }
        public static Dictionary<string, object> Map(object value) { return value as Dictionary<string, object> ?? new Dictionary<string, object>(); }
        public static object Get(Dictionary<string, object> map, string key) { object value; return map.TryGetValue(key, out value) ? value : null; }
        public static string Text(Dictionary<string, object> map, string key) { return Convert.ToString(Get(map, key), CultureInfo.InvariantCulture) ?? ""; }
        public static double Number(Dictionary<string, object> map, string key) { double value; return double.TryParse(Text(map, key), NumberStyles.Any, CultureInfo.InvariantCulture, out value) ? value : 0; }
        public static bool Flag(Dictionary<string, object> map, string key) { return object.Equals(Get(map, key), true); }
        public static IEnumerable<Dictionary<string, object>> Rows(Dictionary<string, object> map, string key) {
            var items = Get(map, key) as IEnumerable;
            if (items == null || items is string) yield break;
            foreach (var item in items) if (item is Dictionary<string, object>) yield return (Dictionary<string, object>)item;
        }
        public static string Content(object value) {
            if (value is string) return (string)value;
            var items = value as IEnumerable;
            if (items == null) return "";
            var text = new System.Text.StringBuilder();
            foreach (var item in items) { var part = Map(item); if (Text(part, "type") == "text") text.Append(Text(part, "text")); }
            return text.ToString();
        }
    }
    public class AccountSession {
        public string Email = "", Token = "", RefreshToken = "", HomeSession = "", DeviceId = "";
        public double ExpiresAt;
        public bool SignedIn { get { return Token.StartsWith("trk_live_") && RefreshToken.StartsWith("trk_refresh_") && HomeSession.Length > 0; } }
    }
    public class ApiException : Exception {
        public readonly int Status;
        public ApiException(string message, int status) : base(message) { Status = status; }
    }
}
