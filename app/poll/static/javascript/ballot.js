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
    let ballot = $('#ballot');
    let rank = (
        '<li class="sort m-1" id="rank-' + team_handle + '">' +
            '<div class="card">' +
                '<div class="card-header">' +
                    '<span class="rank">' + (ballot.children().length + 1) + '</span>' +
                    '<img class="team-logo me-1" src="/static/images/full60/' + team_handle + '.png" alt="">' +
                    teams[team_handle].name +
                    '<button class="btn btn-close remove-rank float-end" value="' + team_handle + '" aria-label="Close"></button>' +
                '</div>' +
            '</div>' +
            '<input type="hidden" class="team-handle" value="'+ team_handle + '">' +
        '</li>'
    );
    ballot.append(rank);
    $(".remove-rank").click(function() {
        let team_handle = $(this)[0].value;
        removeTeamFromBallot(team_handle);
    });
    $('.add-button').filter(function(){return this.value === team_handle}).addClass('d-none');
    $('.remove-button').filter(function(){return this.value === team_handle}).removeClass('d-none');
    resetRankings();
    $('#current-teams').text(ballot.children().length)
}

function removeTeamFromBallot(team_handle) {
    $('#rank-' + team_handle).remove();
    $('.remove-button').filter(function(){return this.value === team_handle}).addClass('d-none');
    $('.add-button').filter(function(){return this.value === team_handle}).removeClass('d-none');
    resetRankings();
    $('#current-teams').text($('#ballot').children().length)
}

function resetRankings() {
    $('#ballot span').each(function (i) {
        $(this).text(i + 1);
    });
}

function saveBallot(page) {
    $('#page').val(page)

    let entries = $('#entries').children();
    let teams = $('#ballot').children();
    if (teams) {
        for (let i = 0; i < teams.length; i++) {
            $(entries[i]).val($(teams[i]).find('.team-handle').val())
        }
    }

    $('#save-form').submit()
}
