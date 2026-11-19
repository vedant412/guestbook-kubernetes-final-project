$(document).ready(function() {
  var entriesElement = $("#guestbook-entries");
  var formElement = $("#guestbook-form");
  var submitElement = $("#guestbook-submit");
  var entryContentElement = $("#guestbook-entry-content");
  var hostAddressElement = $("#guestbook-host-address");

  var appendGuestbookEntries = function(data) {
    entriesElement.empty();
    $.each(data, function(key, val) {
      $("<p>").text(val).appendTo(entriesElement);
    });
  }

  var handleSubmission = function(e) {
    e.preventDefault();
    var entryValue = entryContentElement.val().trim();
    if (entryValue.length > 0) {
      entriesElement.append("<p>...</p>");
      $.getJSON("rpush/guestbook/" + encodeURIComponent(entryValue), appendGuestbookEntries);
      entryContentElement.val("");
    }
    return false;
  }

  submitElement.click(handleSubmission);
  formElement.submit(handleSubmission);
  hostAddressElement.text(document.URL);

  // Poll every second.
  (function fetchGuestbook() {
    $.getJSON("lrange/guestbook").done(appendGuestbookEntries).always(
      function() {
        setTimeout(fetchGuestbook, 1000);
      });
  })();
});
