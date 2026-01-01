import unittest

from vericase.api.app.email_headers import (
    get_header_all,
    get_header_first,
    parse_date_header,
    parse_received_headers,
    parse_rfc822_headers,
    received_time_bounds,
)


class TestEmailHeaders(unittest.TestCase):
    def test_received_parsing(self) -> None:
        raw_headers = (
            "Received: from mail.example.com by mx.google.com; Tue, 01 Aug 2023 10:00:00 +0000\n"
            "Received: from laptop by mail.example.com; Tue, 01 Aug 2023 09:59:00 +0000\n"
            "Date: Tue, 01 Aug 2023 10:00:00 +0000\n"
        )

        msg = parse_rfc822_headers(raw_headers)
        received_values = get_header_all(msg, "Received")
        self.assertEqual(len(received_values), 2)

        hops = parse_received_headers(received_values)
        self.assertEqual(hops[0].received_from, "mail.example.com")
        self.assertEqual(hops[0].received_by, "mx.google.com")
        self.assertTrue(hops[0].parsed_ok)

        first, last = received_time_bounds(hops)
        self.assertEqual(first, "2023-08-01T09:59:00+00:00")
        self.assertEqual(last, "2023-08-01T10:00:00+00:00")

        header_date = parse_date_header(get_header_first(msg, "Date"))
        self.assertEqual(header_date, "2023-08-01T10:00:00+00:00")


if __name__ == "__main__":
    unittest.main()
