const teams = JSON.parse(document.getElementById('team-data').textContent);

$(function() {
    $("#ballot").sortable({
        itemSelector: "li.sort",
        update: function(event, ui) {
            resetRankings();
        }
    });

    $(".add-button").click(function() {
        let team_handle = $(this)[0].value;

        if ($('#ballot').children().length < 25) {
            addTeamToBallot(team_handle)
        } else {
            $('#alertPlaceholder').append(
                '<div class="alert alert-warning alert-dismissible" role="alert">' +
                    'Cannot exceed 25 teams.' +
                    '<button type="button" class="btn-close" data-bs-dismiss="alert" aria-label="Close"></button>' +
                '</div>'
            );
        }
    });

    $(".remove-button").click(function() {
        let team_handle = $(this)[0].value;
        removeTeamFromBallot(team_handle);
    });

    $("#reasons-button").click(function() {
        saveBallot('reasons');
    });
    $("#save-button").click(function() {
        saveBallot('teams');
    });
    $("#validate-button").click(function() {
        saveBallot('validate');
    });
});

function addTeamToBallot(team_handle) {
    let rank = (
        '<li class="sort m-1" id="rank-' + team_handle + '" value="' + team_handle + '">' +
            '<div class="card">' +
                '<div class="card-header">' +
                    '<span class="rank">' + ($('#ballot').children().length + 1) + '</span>' +
                    '<img class="team-logo me-1" src="/static/images/full60/' + team_handle + '.png" alt="">' +
                    teams[team_handle].name +
                    '<button class="btn btn-close remove-rank float-end" value="' + team_handle + '" aria-label="Close"></button>' +
                '</div>' +
            '</div>' +
        '</li>'
    );
    $('#ballot').append(rank);
    $(".remove-rank").click(function() {
        let team_handle = $(this)[0].value;
        removeTeamFromBallot(team_handle);
    });
    $('.add-button').filter(function(){return this.value==team_handle}).addClass('d-none');
    $('.remove-button').filter(function(){return this.value==team_handle}).removeClass('d-none');
    resetRankings();
    $('#current-teams').text($('#ballot').children().length)
}

function removeTeamFromBallot(team_handle) {
    $('#rank-' + team_handle).remove();
    $('.remove-button').filter(function(){return this.value==team_handle}).addClass('d-none');
    $('.add-button').filter(function(){return this.value==team_handle}).removeClass('d-none');
    resetRankings();
    $('#current-teams').text($('#ballot').children().length)
}

function resetRankings() {
    $('#ballot span').each(function (i) {
        $(this).text(i + 1);
    });
}

function saveBallot(page) {
    let ballot_id = $('#ballot-id')[0].value
    let poll_type = $("#poll-type option:selected").text();
    let overall_rationale = encodeURIComponent($("#overall-rationale").text());

    let entries = [];
    let teams = $('#ballot').children();
    for (i = 0; i < teams.length; i++) {
        let entry = {
            rank: i + 1,
            team: $(teams[i])[0].value
        };
        entries.push(entry);
    }
    post('/ballot/save/' + ballot_id + '/', {
        page: page,
        poll_type: poll_type,
        overall_rational: overall_rationale,
        entries: entries
    });
}

function post(path, parameters) {
    var form = $('<form></form>');

    form.attr("method", "post");
    form.attr("action", path);

    $.each(parameters, function(key, value) {
        var field = $('<input></input>');

        field.attr("type", "hidden");
        field.attr("name", key);
        field.attr("value", value);

        form.append(field);
    });

    // The form needs to be a part of the document in
    // order for us to be able to submit it.
    $(document.body).append(form);
    form.submit();
}
