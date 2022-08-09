$(function() {
    $("#teams-button").click(function() {
        saveBallot('teams');
    });
    $("#save-button").click(function() {
        saveBallot('reasons');
    });
    $("#validate-button").click(function() {
        saveBallot('validate');
    });
    $("textarea").each(function () {
        this.setAttribute("style", "height:" + (this.scrollHeight) + "px;overflow-y:hidden;");
    }).on("input", function () {
        this.style.height = "auto";
        this.style.height = (this.scrollHeight) + "px";
    });
});

function saveBallot(page) {
    $('#page').val(page)
    $('#save-form').submit()
}
