### Feature Request: Nostr Zap Notifications

**Summary:**
Integrate Nostr functionality to monitor for "zaps" (micro-payments via Lightning) sent to a configured user identity (`npub`) and display a notification on the device's screen.

**Proposed Changes:**

1.  **Configuration:**
    *   Modify `Source/device_keys.json` to include two new keys:
        *   `nostr_npub`: The user's Nostr public key (e.g., "npub1...").
        *   `nostr_relays`: A JSON array of preferred Nostr relay URLs (e.g., `["wss://relay.damus.io"]`).

2.  **New Libraries:**
    *   Add the following pure Python libraries to the `Source/lib/` directory to handle Nostr communication without requiring custom firmware:
        *   `bech32.py`: For converting the `npub` into a hex public key for API filters.
        *   `cpwebsockets`: A websocket client for connecting to Nostr relays.
        *   `adafruit_logging`: A dependency for `cpwebsockets`.

3.  **Core Logic (`code.py`):**
    *   **Nostr Client:** Implement a simple, read-only Nostr client.
        *   On startup, load the `npub` and `nostr_relays` from the configuration.
        *   Convert the `npub` to its hex representation.
        *   Establish a non-blocking websocket connection to a random relay from the list.
    *   **Zap Subscription:**
        *   Send a `REQ` message to the connected relay to subscribe to Nostr events.
        *   The filter should target `kind: 9735` (Zap Receipt) where the `#p` tag matches the user's hex public key.
        *   Use a `since` filter with the current timestamp to only fetch new zaps.
    *   **Event Handling:**
        *   In the main loop, continuously check the websocket for incoming `EVENT` messages.
        *   When a valid zap event is received, parse its `description` tag to extract the zap `amount` (in millisats).
        *   The `description` tag of the `kind: 9735` event also contains a JSON-encoded `kind: 9734` event (the zap request). Parse this JSON to access the `pubkey` of the sender.

4.  **Display Integration:**
    *   When a new zap is detected, format a notification string (e.g., "ZAP! 1,000 sats").
    *   Prepend this notification to the existing scrolling ticker message.
    *   Immediately trigger the ticker scroll to ensure the user sees the notification promptly.
    *   **Future Enhancement: Sender Identification in Zap Notifications**
        *   The `pubkey` of the zap sender, already extracted from the zap request (kind 9734 event within the description tag), can be used to identify the sender in the notification.
        *   This could involve converting the sender's `pubkey` to an `npub` and truncating it (e.g., `npub1sg6pl...u63q0uf63m`) to be displayed.
        *   Alternatively, a `kind: 0` lookup for the sender's `pubkey` could be performed to find and display a NIP-05 identifier (e.g., `user@domain.com`).
        *   The goal is to update the notification string to include the sender's identifier, for example: "ZAP! 1,000 sats from {sender}".
